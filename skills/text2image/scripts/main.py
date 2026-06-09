import argparse
import json
import os
from pathlib import Path
import sys
from datetime import datetime
import time

import requests

from auth.auth_client import with_auth, get_headers

BASE_URL = "http://121.40.167.37:5000"
ENDPOINT = "/api/generate-image"
DEFAULT_OUTPUT_DIR = str(Path.home() / "Desktop" / "text2image")

ASPECT_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
IMAGE_SIZES = ["1K", "2K", "4K"]
MODELS = [
    "gemini-3.1-flash-image-preview",  # 别名: banana-2
    "gemini-3-pro-image-preview",      # 别名: banana-pro
]
TIMEOUT = 240

@with_auth
def _request(url, fields, files=None):
    if files:
        return requests.post(url, data=fields, files=files, headers=get_headers(), timeout=TIMEOUT)
    return requests.post(url, json=fields, headers=get_headers(), timeout=TIMEOUT)


def generate(args: argparse.Namespace):
    url = f"{BASE_URL}{ENDPOINT}"
    output_dir = args.output_dir
    model = args.model
    file_urls = [u.strip() for u in args.file_urls.split(",") if u.strip()] if args.file_urls else []
    local_files = [f.strip() for f in args.files.split(",") if f.strip()] if args.files else []

    fields = {
        "prompt": args.prompt,
        "requestId": f"cli-{int(time.time() * 1000)}",
        "model": model,
        "aspectRatio": args.aspect_ratio,
        "imageSize": args.image_size,
        "fileUrls": json.dumps(file_urls) if file_urls else None,
    }
    fields = {k: v for k, v in fields.items() if v is not None}

    try:
        if local_files:
            files = [("files", (os.path.basename(p), open(p, "rb"))) for p in local_files]
            resp = _request(url, fields, files=files)
            for _, (_, f) in files:
                f.close()
        else:
            resp = _request(url, fields)

        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if ct.startswith("image/"):
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')}.png")
            with open(out_path, "wb") as f:
                f.write(resp.content)
            print(json.dumps({"success": True, "file": out_path}))
        else:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except requests.HTTPError as e:
        try:
            err_json = e.response.json()
            msg = err_json.get("message", f"HTTP {e.response.status_code}")
        except Exception:
            msg = e.response.text[:500] or f"HTTP {e.response.status_code}"
        print(json.dumps({"success": False, "message": msg}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except requests.ConnectionError as e:
        print(json.dumps({"success": False, "message": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="文生图 CLI")
    parser.add_argument("--prompt", required=True, help="提示词")
    parser.add_argument("--aspect-ratio", choices=ASPECT_RATIOS, help="输出比例")
    parser.add_argument("--image-size", choices=IMAGE_SIZES, default=None, help="分辨率: 1K/2K/4K")
    parser.add_argument("--model", choices=MODELS, default=None, help="模型: gemini-3.1-flash-image-preview (banana-2) / gemini-3-pro-image-preview (banana-pro)")
    parser.add_argument("--file-urls", default=None, help="参考图 URL，逗号分隔")
    parser.add_argument("--files", default=None, help="本地参考图文件路径，逗号分隔")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录，默认 ~/Desktop/text2image")
    args = parser.parse_args()
    generate(args)


if __name__ == "__main__":
    main()
