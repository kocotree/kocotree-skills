import json
import logging
import os
import sys
import time
from functools import wraps
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://121.40.167.37:5050")
_DEFAULT_TOKEN_PATH = os.path.join(Path.home(), ".kocotree-skills", "auth.json")
_token_path = os.getenv("AUTH_TOKEN_PATH", _DEFAULT_TOKEN_PATH)
_pending_path = os.path.join(Path.home(), ".kocotree-skills", ".auth_pending")
_token_cache = None

POLL_INTERVAL = 3
POLL_TIMEOUT = 60
PENDING_EXPIRE = 300
_TOKEN_RESPONSE_FIELDS = frozenset({
    "access_token",
    "refresh_token",
    "token_type",
    "expires_in",
    "refresh_token_expires_in",
    "refresh_expires_in",
    "scope",
})
_USER_INFO_FIELDS = ("name", "open_id")


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


def _write_token(token_data):
    """将完整认证数据写入本地文件并更新内存缓存。

    功能说明：
        原样持久化已经组装完成的认证数据，不重新计算 Token 有效期。

    参数：
        token_data：需要写入本地认证文件的完整数据。

    返回值：
        None。
    """
    global _token_cache
    token_dir = os.path.dirname(_token_path)
    if token_dir:
        os.makedirs(token_dir, exist_ok=True)
    saved_data = dict(token_data)
    with open(_token_path, "w", encoding="utf-8") as f:
        json.dump(saved_data, f, indent=2, ensure_ascii=False)
    _token_cache = saved_data


def _save_token(token_data):
    """保存 Token 数据并计算访问凭证的绝对过期时间。

    功能说明：
        根据飞书返回的相对有效期计算绝对过期时间，再持久化完整认证数据。

    参数：
        token_data：包含 Token、有效期及可选用户信息的认证数据。

    返回值：
        None。
    """
    saved_data = dict(token_data)
    now = int(time.time())
    refresh_expires_in = saved_data.get(
        "refresh_token_expires_in",
        saved_data.get("refresh_expires_in", 604800),
    )
    saved_data["access_token_expires_at"] = (
        now + saved_data.get("expires_in", 7200)
    )
    saved_data["refresh_token_expires_at"] = now + refresh_expires_in
    _write_token(saved_data)


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


def _merge_refreshed_token(current_data, refreshed_data):
    """将刷新响应中的 Token 字段合并到现有认证数据。

    功能说明：
        仅接受明确的 Token 响应字段，保留现有姓名、用户标识和其他本地数据。

    参数：
        current_data：刷新前的完整本地认证数据。
        refreshed_data：认证服务返回的新 Token 数据。

    返回值：
        dict：合并后的完整认证数据。
    """
    merged_data = dict(current_data)
    for field in _TOKEN_RESPONSE_FIELDS:
        if field in refreshed_data:
            merged_data[field] = refreshed_data[field]
    return merged_data


def _sync_user_info(access_token):
    """使用新访问凭证查询并更新本地用户信息。

    功能说明：
        调用认证服务验证接口查询最新用户信息；查询失败时保留本地已有信息，
        不影响已经完成的 Token 刷新。

    参数：
        access_token：刷新后用于查询用户信息的新访问凭证。

    返回值：
        bool：用户信息查询并写入成功时返回 True，否则返回 False。
    """
    logger.info("开始同步用户信息")
    try:
        resp = requests.get(
            f"{AUTH_SERVICE_URL}/api/v1/auth/verify",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("用户信息查询失败，保留本地已有信息：%s", exc)
        return False

    user_info = result.get("data")
    if result.get("code") != 0 or not isinstance(user_info, dict):
        logger.warning(
            "用户信息查询未成功，保留本地已有信息：%s",
            result.get("msg", "未知错误"),
        )
        return False

    data = dict(_load_token() or {})
    for field in _USER_INFO_FIELDS:
        if field in user_info:
            data[field] = user_info[field]
    _write_token(data)
    logger.info("用户信息同步成功")
    return True


def _refresh():
    """刷新访问凭证并同步用户信息。

    功能说明：
        使用本地 refresh_token 获取新 Token，仅更新 Token 相关字段并先行保存，
        随后查询最新用户信息；用户信息查询失败不影响 Token 刷新结果。

    参数：
        无。

    返回值：
        bool：Token 刷新并保存成功时返回 True，否则返回 False。
    """
    current_data = _load_token()
    if not current_data or not current_data.get("refresh_token"):
        logger.warning("本地没有可用的 refresh_token，无法刷新")
        return False

    logger.info("开始刷新访问凭证")
    try:
        resp = requests.post(
            f"{AUTH_SERVICE_URL}/api/v1/auth/refresh",
            json={"refresh_token": current_data["refresh_token"]},
            timeout=10,
        )
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("访问凭证刷新请求失败：%s", exc)
        return False

    refreshed_data = result.get("data")
    if (
        result.get("code") != 0
        or not isinstance(refreshed_data, dict)
        or not refreshed_data.get("access_token")
    ):
        logger.warning(
            "访问凭证刷新未成功：%s",
            result.get("msg", "响应缺少 access_token"),
        )
        return False

    merged_data = _merge_refreshed_token(current_data, refreshed_data)
    _save_token(merged_data)
    logger.info("访问凭证刷新并保存成功")
    _sync_user_info(merged_data["access_token"])
    return True


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
