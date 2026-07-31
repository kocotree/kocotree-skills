"""Skill 客户端：飞书 OAuth 认证，管理本地 token，自动刷新。

使用方式：
    from auth_client import with_auth, get_headers

    @with_auth
    def fetch_data():
        return requests.get("http://other-service/api/data", headers=get_headers())

    result = fetch_data()
    # 首次（无 token）：
    #   第 1 次调用 → 打印授权链接 → 脚本退出
    #   用户完成浏览器授权后
    #   第 2 次调用 → 自动轮询获取 token → 保存 → 继续业务逻辑
    # 后续：直接带 token 请求，过期自动刷新

环境变量：
    AUTH_SERVICE_URL  auth 服务地址，默认 http://localhost:5050
    AUTH_TOKEN_PATH   本地 token 存储路径，默认 ~/.kocotree-skills/auth.json
"""

import json
import os
import sys
import time
from functools import wraps
from pathlib import Path

import requests

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://121.40.167.37:5050")
_DEFAULT_TOKEN_PATH = os.path.join(Path.home(), ".kocotree-skills", "auth.json")
_token_path = os.getenv("AUTH_TOKEN_PATH", _DEFAULT_TOKEN_PATH)
_pending_path = os.path.join(Path.home(), ".kocotree-skills", ".auth_pending")
_token_cache = None

POLL_INTERVAL = 3
POLL_TIMEOUT = 60
PENDING_EXPIRE = 300


def _save_pending(state, authorize_url):
    os.makedirs(os.path.dirname(_pending_path), exist_ok=True)
    with open(_pending_path, "w", encoding="utf-8") as f:
        json.dump({"state": state, "authorize_url": authorize_url,
                    "created_at": int(time.time())}, f)


def _load_pending():
    try:
        with open(_pending_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("created_at", 0) > PENDING_EXPIRE:
            _clear_pending()
            return None
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _clear_pending():
    try:
        os.remove(_pending_path)
    except FileNotFoundError:
        pass


def _load_token():
    global _token_cache
    if _token_cache is not None:
        return _token_cache
    try:
        with open(_token_path, "r", encoding="utf-8") as f:
            _token_cache = json.load(f)
            return _token_cache
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_token(token_data):
    global _token_cache
    os.makedirs(os.path.dirname(_token_path), exist_ok=True)
    now = int(time.time())
    token_data["access_token_expires_at"] = now + token_data.get("expires_in", 7200)
    token_data["refresh_token_expires_at"] = now + token_data.get("refresh_expires_in", 604800)
    with open(_token_path, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)
    _token_cache = token_data


def _is_access_token_expired():
    data = _load_token()
    if not data or "access_token" not in data:
        return True
    return time.time() >= data.get("access_token_expires_at", 0)


def _is_refresh_token_expired():
    data = _load_token()
    if not data or "refresh_token" not in data:
        return True
    return time.time() >= data.get("refresh_token_expires_at", 0)


def _refresh():
    """用 refresh_token 刷新 access_token。"""
    data = _load_token()
    if not data:
        return False
    resp = requests.post(f"{AUTH_SERVICE_URL}/api/v1/auth/refresh", json={
        "refresh_token": data["refresh_token"],
    }, timeout=10)
    result = resp.json()
    if result.get("code") == 0:
        _save_token(result["data"])
        return True
    return False


def _get_auth_url():
    """请求 auth 服务获取飞书授权链接和 state。"""
    resp = requests.get(f"{AUTH_SERVICE_URL}/api/v1/auth/login", timeout=10)
    result = resp.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to get authorize URL: {result.get('msg')}")
    return result["data"]["authorize_url"], result["data"]["state"]


def _poll_token(state):
    """轮询 auth 服务等待用户完成授权，成功后保存 token。"""
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
                print("授权成功。", flush=True)
                return True
        except requests.RequestException:
            pass
    return False


def ensure_token():
    """确保本地有有效的 access_token。

    状态机：
      有效 token       → 直接返回
      可刷新           → 刷新后返回
      有 pending       → 轮询服务端，成功返回，超时则清除 pending 抛异常
      无 token 无 pending → 发起授权，保存 pending，打印链接，退出脚本
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


def get_headers():
    """返回带 Authorization 的 headers dict。"""
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
