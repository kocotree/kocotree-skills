"""认证客户端：飞书 OAuth 授权 + token 管理。

与 text2image 共用同一套 auth 服务和本地 token 文件（~/.kocotree-skills/auth.json），
已授权过的用户无需重复登录。
"""
from __future__ import annotations

import json
import os
import sys
import time
from functools import wraps
from pathlib import Path

import requests

from core.utils import get_logger

logger = get_logger(__name__)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://121.40.167.37:5050")
_DEFAULT_TOKEN_PATH = os.path.join(Path.home(), ".kocotree-skills", "auth.json")
_token_path = os.getenv("AUTH_TOKEN_PATH", _DEFAULT_TOKEN_PATH)
_pending_path = os.path.join(Path.home(), ".kocotree-skills", ".auth_pending")
_token_cache: dict | None = None

POLL_INTERVAL = 3
POLL_TIMEOUT = 60
PENDING_EXPIRE = 300


def _save_pending(state: str, authorize_url: str) -> None:
    os.makedirs(os.path.dirname(_pending_path), exist_ok=True)
    with open(_pending_path, "w", encoding="utf-8") as f:
        json.dump({"state": state, "authorize_url": authorize_url,
                    "created_at": int(time.time())}, f)


def _load_pending() -> dict | None:
    try:
        with open(_pending_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("created_at", 0) > PENDING_EXPIRE:
            _clear_pending()
            return None
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _clear_pending() -> None:
    try:
        os.remove(_pending_path)
    except FileNotFoundError:
        pass


def _load_token() -> dict | None:
    global _token_cache
    if _token_cache is not None:
        return _token_cache
    try:
        with open(_token_path, "r", encoding="utf-8") as f:
            _token_cache = json.load(f)
            return _token_cache
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_token(token_data: dict) -> None:
    global _token_cache
    os.makedirs(os.path.dirname(_token_path), exist_ok=True)
    now = int(time.time())
    token_data["access_token_expires_at"] = now + token_data.get("expires_in", 7200)
    token_data["refresh_token_expires_at"] = now + token_data.get("refresh_expires_in", 604800)
    with open(_token_path, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)
    _token_cache = token_data


def _is_access_token_expired() -> bool:
    data = _load_token()
    if not data or "access_token" not in data:
        return True
    return time.time() >= data.get("access_token_expires_at", 0)


def _is_refresh_token_expired() -> bool:
    data = _load_token()
    if not data or "refresh_token" not in data:
        return True
    return time.time() >= data.get("refresh_token_expires_at", 0)


def _refresh() -> bool:
    """用 refresh_token 刷新 access_token。"""
    data = _load_token()
    if not data:
        return False
    try:
        resp = requests.post(f"{AUTH_SERVICE_URL}/api/v1/auth/refresh", json={
            "refresh_token": data["refresh_token"],
        }, timeout=10)
        result = resp.json()
        if result.get("code") == 0:
            _save_token(result["data"])
            logger.info("access_token 已刷新")
            return True
    except requests.RequestException as exc:
        logger.warning("刷新 token 失败: %s", exc)
    return False


def _get_auth_url() -> tuple[str, str]:
    """请求 auth 服务获取飞书授权链接和 state。"""
    resp = requests.get(f"{AUTH_SERVICE_URL}/api/v1/auth/login", timeout=10)
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"获取授权链接失败: {result.get('msg')}")
    return result["data"]["authorize_url"], result["data"]["state"]


def _poll_token(state: str) -> bool:
    """轮询 auth 服务等待用户完成授权。"""
    start = time.time()
    while time.time() - start < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        try:
            resp = requests.get(
                f"{AUTH_SERVICE_URL}/api/v1/auth/poll",
                params={"state": state},
                timeout=10,
            )
            result = resp.json()
            if result.get("code") == 0:
                _save_token(result["data"])
                logger.info("授权成功")
                return True
        except requests.RequestException:
            pass
    return False


def ensure_token() -> None:
    """确保本地有有效的 access_token。

    状态机：有效 → 直接返回；可刷新 → 刷新；有 pending → 轮询；
    无 token 无 pending → 发起授权、打印链接、退出脚本。
    """
    if not _is_access_token_expired():
        return

    if not _is_refresh_token_expired():
        if _refresh():
            return

    pending = _load_pending()
    if pending:
        if _poll_token(pending["state"]):
            _clear_pending()
            return
        _clear_pending()
        raise RuntimeError("授权超时，请重新发起。")

    authorize_url, state = _get_auth_url()
    _save_pending(state, authorize_url)
    print(f"请在浏览器中打开以下链接完成飞书授权：\n{authorize_url}", flush=True)
    print("完成授权后，请重新运行此脚本。", flush=True)
    sys.exit(0)


def get_headers() -> dict[str, str]:
    """返回带 Authorization 的 headers。"""
    ensure_token()
    data = _load_token()
    if data and data.get("access_token"):
        return {"Authorization": f"Bearer {data['access_token']}"}
    return {}


def with_auth(f):
    """装饰器：确保 token 有效后执行，401 时自动刷新重试。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        ensure_token()
        resp = f(*args, **kwargs)
        try:
            data = resp.json()
        except (ValueError, AttributeError):
            return resp
        if resp.status_code == 401 or data.get("code") == 401:
            global _token_cache
            _token_cache = None
            ensure_token()
            resp = f(*args, **kwargs)
        return resp
    return decorated
