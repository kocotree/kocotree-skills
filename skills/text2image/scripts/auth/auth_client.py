import json
import os
from functools import wraps
from pathlib import Path

_DEFAULT_KEY_PATH = os.path.join(Path.home(), ".kocotree-skills", "auth.json")
_key_path = os.getenv("AUTH_KEY_PATH", _DEFAULT_KEY_PATH)
_key_cache = None


def _load_key():
    global _key_cache
    if _key_cache:
        return _key_cache
    try:
        with open(_key_path, "r", encoding="utf-8") as f:
            _key_cache = json.load(f)
            return _key_cache
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_key(key_data):
    global _key_cache
    os.makedirs(os.path.dirname(_key_path), exist_ok=True)
    with open(_key_path, "w", encoding="utf-8") as f:
        json.dump(key_data, f, indent=2, ensure_ascii=False)
    _key_cache = key_data


def get_headers():
    """返回带 Authorization 的 headers dict，没有 key 则返回空 dict。"""
    data = _load_key()
    api_key = data.get("api_key") if data else None
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def with_auth(f):
    """装饰器：自动处理 code=100（key 创建）响应，保存 key 后重试。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        resp = f(*args, **kwargs)
        try:
            data = resp.json()
        except (ValueError, AttributeError):
            return resp
        if data.get("code") == 100 and data.get("msg") == "key_created":
            _save_key(data["data"])
            resp = f(*args, **kwargs)
        return resp

    return decorated
