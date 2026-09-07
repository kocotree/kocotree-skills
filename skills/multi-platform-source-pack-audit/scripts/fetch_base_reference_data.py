#!/usr/bin/env python3
"""按 KQ 货号读取飞书多维表商品资料及附件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cleanup_work import DEFAULT_WORK_DIR, cleanup_work_directory


LOGGER = logging.getLogger("base_reference_data_fetcher")
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CONFIG = SKILL_DIR / "assets" / "configs" / "reference-data-sources.json"
WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ReferenceDataError(RuntimeError):
    """表示多维表访问、配置或数据解析失败。"""


def configure_logging(level: str) -> None:
    """配置标准日志输出。

    参数：
        level: 日志级别名称，例如 INFO 或 WARNING。

    返回值：
        无。
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def calculate_sha256(path: Path) -> str:
    """计算文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    """读取并校验商品资料来源配置。

    参数：
        path: 商品资料来源 JSON 配置路径。

    返回值：
        已完成基础结构校验的配置字典。
    """

    resolved = path.resolve()
    data = json.loads(resolved.read_text(encoding="utf-8"))
    required = {"schema_version", "identity", "base_token", "tables", "nas"}
    missing = sorted(required - set(data))
    if missing:
        raise ValueError(f"商品资料来源配置缺少字段：{missing}")
    if data["identity"] != "user":
        raise ValueError("商品资料来源配置 identity 必须为 user")
    for key in ("style_external", "sku_external", "style_source"):
        if key not in data["tables"]:
            raise ValueError(f"商品资料来源配置缺少数据表：{key}")
    return data


def run_lark_json(arguments: list[str]) -> dict[str, Any]:
    """运行 lark-cli 并解析 JSON 响应。

    参数：
        arguments: `lark-cli` 命令名之后的参数列表。

    返回值：
        lark-cli 返回的 JSON 对象。
    """

    executable = shutil.which("lark-cli")
    if executable is None:
        raise ReferenceDataError("未找到 lark-cli，请先安装并完成飞书配置")
    environment = os.environ.copy()
    environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    command = [executable, *arguments]
    LOGGER.debug("执行飞书只读命令：%s", " ".join(arguments[:3]))
    completed = subprocess.run(
        command,
        cwd=SCRIPT_DIR,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    payload_text = completed.stdout.strip() or completed.stderr.strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ReferenceDataError(
            f"lark-cli 未返回有效 JSON，退出码={completed.returncode}"
        ) from exc
    if completed.returncode != 0 or payload.get("ok") is False:
        error = payload.get("error", {})
        message = error.get("message") or payload_text
        hint = error.get("hint")
        if hint:
            message = f"{message}；{hint}"
        raise ReferenceDataError(str(message))
    return payload


def verify_user_identity() -> dict[str, Any]:
    """验证 lark-cli 用户身份和令牌状态。

    参数：
        无。

    返回值：
        当前用户身份的非敏感状态信息。
    """

    payload = run_lark_json(["auth", "status", "--json", "--verify"])
    user = payload.get("identities", {}).get("user", {})
    if (
        payload.get("verified") is not True
        or user.get("status") != "ready"
        or user.get("tokenStatus") != "valid"
    ):
        raise ReferenceDataError("飞书用户身份未就绪，请先完成 lark-cli 用户授权")
    LOGGER.info("飞书用户身份验证通过：%s", user.get("userName", "当前用户"))
    return {
        "status": user.get("status"),
        "verified": payload.get("verified"),
        "token_status": user.get("tokenStatus"),
        "user_name": user.get("userName"),
    }


def matrix_to_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """将 record-list 矩阵响应转换为字段字典列表。

    参数：
        payload: `base +record-list --format json` 的响应。

    返回值：
        每项包含 `record_id` 和字段值的记录列表。
    """

    data = payload.get("data", {})
    if data.get("has_more") is True:
        raise ReferenceDataError("单款查询结果超过 200 条，请收紧数据范围后重试")
    fields = data.get("fields", [])
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    if not (len(rows) == len(record_ids)):
        raise ReferenceDataError("多维表记录矩阵与 record_id 数量不一致")
    records: list[dict[str, Any]] = []
    for record_id, row in zip(record_ids, rows, strict=True):
        if len(row) != len(fields):
            raise ReferenceDataError(f"记录 {record_id} 的字段数量与表头不一致")
        records.append({"record_id": record_id, **dict(zip(fields, row, strict=True))})
    return records


def query_records(
    base_token: str,
    table: dict[str, Any],
    lookup_value: str,
) -> list[dict[str, Any]]:
    """按配置字段查询单款记录。

    参数：
        base_token: 飞书 Base Token。
        table: 包含表 ID、查询字段和业务字段映射的配置。
        lookup_value: 当前查询使用的 KQ 货号或设计编码。

    返回值：
        匹配到的结构化记录列表。
    """

    filter_payload = {
        "logic": "and",
        "conditions": [
            [
                table["lookup_field"],
                table.get("lookup_operator", "=="),
                lookup_value,
            ]
        ],
    }
    arguments = [
        "base",
        "+record-list",
        "--base-token",
        base_token,
        "--table-id",
        table["table_id"],
    ]
    for field_name in table["fields"].values():
        arguments.extend(["--field-id", field_name])
    arguments.extend(
        [
            "--filter-json",
            json.dumps(filter_payload, ensure_ascii=False, separators=(",", ":")),
            "--limit",
            "200",
            "--as",
            "user",
            "--format",
            "json",
        ]
    )
    LOGGER.info("查询多维表：%s；匹配值=%s", table["name"], lookup_value)
    records = matrix_to_records(run_lark_json(arguments))
    LOGGER.info("多维表查询完成：%s；记录=%s", table["name"], len(records))
    return records


def is_missing(value: Any, markers: set[str]) -> bool:
    """判断多维表字段是否属于缺失状态。"""

    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in markers
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def collect_design_codes(
    records: list[dict[str, Any]],
    field_name: str,
    markers: set[str],
) -> list[str]:
    """从查询记录中提取唯一设计编码。"""

    values = {
        str(record.get(field_name)).strip()
        for record in records
        if not is_missing(record.get(field_name), markers)
    }
    return sorted(values)


def collect_missing_fields(
    records: list[dict[str, Any]],
    table: dict[str, Any],
    markers: set[str],
) -> dict[str, list[str]]:
    """统计必需业务字段的缺失记录。

    参数：
        records: 当前数据表匹配记录。
        table: 数据表字段映射和必需业务角色配置。
        markers: 视为缺失的文本标记集合。

    返回值：
        以业务角色为键、缺失记录 ID 列表为值的字典。
    """

    missing: dict[str, list[str]] = {}
    for role in table.get("required_roles", []):
        field_name = table["fields"][role]
        record_ids = [
            str(record["record_id"])
            for record in records
            if is_missing(record.get(field_name), markers)
        ]
        if not records:
            record_ids = ["record_not_found"]
        if record_ids:
            missing[role] = record_ids
    return missing


def sanitize_filename(name: str) -> str:
    """生成适用于 Windows 的安全附件文件名。"""

    cleaned = WINDOWS_INVALID_FILENAME.sub("_", name).strip().rstrip(".")
    return cleaned or "attachment"


def ensure_output_directory(path: Path) -> Path:
    """确认输出目录位于 scripts/work 内。

    参数：
        path: 用户指定的资料输出目录。

    返回值：
        已创建的绝对输出目录。
    """

    resolved = path.resolve()
    work_dir = DEFAULT_WORK_DIR.resolve()
    if resolved != work_dir and work_dir not in resolved.parents:
        raise ValueError(f"输出目录必须位于 {work_dir} 内：{resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def download_attachments(
    base_token: str,
    table: dict[str, Any],
    source_records: list[dict[str, Any]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    """按附件业务角色下载来源表文件。

    参数：
        base_token: 飞书 Base Token。
        table: 来源表字段映射和附件角色配置。
        source_records: 来源表匹配记录。
        output_dir: 当前任务的绝对输出目录。

    返回值：
        包含字段角色、附件属性和本地路径的清单。
    """

    downloaded: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for record in source_records:
        record_id = str(record["record_id"])
        for role in table.get("attachment_roles", []):
            field_name = table["fields"][role]
            attachments = record.get(field_name) or []
            if not isinstance(attachments, list):
                raise ReferenceDataError(f"来源表附件字段类型异常：{field_name}")
            role_dir = output_dir / "attachments" / role
            role_dir.mkdir(parents=True, exist_ok=True)
            for index, attachment in enumerate(attachments, start=1):
                token = str(attachment.get("file_token", "")).strip()
                if not token or token in seen_tokens:
                    continue
                seen_tokens.add(token)
                name = sanitize_filename(str(attachment.get("name", "attachment")))
                target = role_dir / f"{index:02d}-{token[:8]}-{name}"
                relative_target = target.relative_to(SCRIPT_DIR).as_posix()
                LOGGER.info("下载多维表附件：%s；%s", role, name)
                run_lark_json(
                    [
                        "base",
                        "+record-download-attachment",
                        "--base-token",
                        base_token,
                        "--table-id",
                        table["table_id"],
                        "--record-id",
                        record_id,
                        "--file-token",
                        token,
                        "--output",
                        relative_target,
                        "--overwrite",
                        "--as",
                        "user",
                        "--format",
                        "json",
                    ]
                )
                downloaded.append(
                    {
                        "role": role,
                        "field": field_name,
                        "record_id": record_id,
                        "file_token": token,
                        "name": attachment.get("name"),
                        "size": attachment.get("size"),
                        "local_path": str(target),
                    }
                )
    return downloaded


def build_attachment_inventory(
    table: dict[str, Any],
    source_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """生成来源表附件清单，不执行下载。"""

    inventory: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for record in source_records:
        for role in table.get("attachment_roles", []):
            field_name = table["fields"][role]
            attachments = record.get(field_name) or []
            if not isinstance(attachments, list):
                raise ReferenceDataError(f"来源表附件字段类型异常：{field_name}")
            for attachment in attachments:
                token = str(attachment.get("file_token", "")).strip()
                if not token or token in seen_tokens:
                    continue
                seen_tokens.add(token)
                inventory.append(
                    {
                        "role": role,
                        "field": field_name,
                        "record_id": record["record_id"],
                        "file_token": token,
                        "name": attachment.get("name"),
                        "size": attachment.get("size"),
                        "local_path": None,
                    }
                )
    return inventory


def fetch_reference_data(
    product_code: str,
    config: dict[str, Any],
    config_path: Path,
    output_dir: Path,
    should_download: bool,
) -> dict[str, Any]:
    """读取当前货号的多维表业务字段和附件。

    参数：
        product_code: 从数据包根目录取得的 KQ 货号。
        config: 已验证的商品资料来源配置。
        config_path: 本次读取的商品资料来源配置路径。
        output_dir: 当前任务资料输出目录。
        should_download: 是否将来源表附件下载到工作目录。

    返回值：
        包含身份状态、匹配记录、字段缺失和 NAS 回退要求的结果。
    """

    identity = verify_user_identity()
    base_token = str(config["base_token"])
    tables = config["tables"]
    markers = {str(item).strip() for item in config.get("missing_markers", [])}

    style_records = query_records(base_token, tables["style_external"], product_code)
    sku_records = query_records(base_token, tables["sku_external"], product_code)
    style_design_field = tables["style_external"]["fields"]["design_code"]
    sku_design_field = tables["sku_external"]["fields"]["design_code"]
    design_codes = sorted(
        set(collect_design_codes(style_records, style_design_field, markers))
        | set(collect_design_codes(sku_records, sku_design_field, markers))
    )
    if (style_records or sku_records) and not design_codes:
        raise ReferenceDataError(
            f"货号 {product_code} 已匹配记录，但没有可用的设计编码"
        )
    if len(design_codes) > 1:
        raise ReferenceDataError(
            f"货号 {product_code} 匹配到多个设计编码：{design_codes}"
        )

    source_records: list[dict[str, Any]] = []
    if design_codes:
        source_records = query_records(
            base_token,
            tables["style_source"],
            design_codes[0],
        )
        if len(source_records) > 1:
            raise ReferenceDataError(
                f"设计编码 {design_codes[0]} 在附件来源表匹配到多条记录"
            )

    style_missing = collect_missing_fields(
        style_records,
        tables["style_external"],
        markers,
    )
    sku_missing = collect_missing_fields(
        sku_records,
        tables["sku_external"],
        markers,
    )
    attachments = build_attachment_inventory(tables["style_source"], source_records)
    if should_download:
        attachments = download_attachments(
            base_token,
            tables["style_source"],
            source_records,
            output_dir,
        )
    report_count = sum(1 for item in attachments if item["role"] == "test_reports")
    product_information_fallback = bool(style_missing or sku_missing)
    result = {
        "schema_version": 1,
        "status": "matched" if style_records or sku_records else "not_found",
        "product_code": product_code,
        "identity": identity,
        "config_sha256": calculate_sha256(config_path.resolve()),
        "base": {
            "access_status": "ready",
            "base_token": base_token,
            "design_codes": design_codes,
            "record_counts": {
                "style_external": len(style_records),
                "sku_external": len(sku_records),
                "style_source": len(source_records),
            },
        },
        "records": {
            "style_external": style_records,
            "sku_external": sku_records,
            "style_source": source_records,
        },
        "missing_fields": {
            "style_external": style_missing,
            "sku_external": sku_missing,
        },
        "attachments": attachments,
        "nas_fallback_required": {
            "product_information": product_information_fallback,
            "logo_reference": True,
            "test_reports": report_count == 0,
        },
        "nas_resolution": {
            "product_information": {
                "required": product_information_fallback,
                "status": "pending" if product_information_fallback else "not_required",
                "matched_paths": [],
                "notes": "",
            },
            "logo_reference": {
                "required": True,
                "status": "pending",
                "matched_paths": [],
                "notes": "",
            },
            "test_reports": {
                "required": report_count == 0,
                "status": "pending" if report_count == 0 else "not_required",
                "matched_paths": [],
                "notes": "",
            },
        },
    }
    LOGGER.info(
        "商品资料读取完成：货号=%s；款记录=%s；码记录=%s；附件=%s",
        product_code,
        len(style_records),
        len(sku_records),
        len(attachments),
    )
    if product_information_fallback:
        LOGGER.warning("多维表存在缺失业务字段，需要访问产品信息 NAS 补充")
    if report_count == 0:
        LOGGER.warning("多维表没有检测报告附件，需要访问检测报告 NAS 补充")
    return result


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含货号、输出目录、配置、附件下载开关和日志级别的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_code", help="需要查询的 KQ 货号")
    parser.add_argument("--output-dir", type=Path, required=True, help="资料输出目录")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="商品资料来源配置",
    )
    parser.add_argument(
        "--download-attachments",
        action="store_true",
        help="下载当前款商品图片、洗唛、合格证和检测报告",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行多维表商品资料读取主流程。

    参数：
        无，参数从命令行读取。

    返回值：
        用户身份和多维表读取成功时返回 0；访问或解析失败时返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    output_dir: Path | None = None
    try:
        product_code = args.product_code.strip().upper()
        if not product_code:
            raise ValueError("KQ 货号不能为空")
        output_dir = ensure_output_directory(args.output_dir)
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[output_dir],
        )
        config = load_config(args.config)
        result = fetch_reference_data(
            product_code=product_code,
            config=config,
            config_path=args.config,
            output_dir=output_dir,
            should_download=args.download_attachments,
        )
        result_path = output_dir / "base-reference-data.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        LOGGER.info("已写入多维表商品资料：%s", result_path)
        cleanup_work_directory(
            work_dir=DEFAULT_WORK_DIR,
            protected_paths=[output_dir],
        )
    except Exception as exc:
        LOGGER.exception("多维表商品资料读取失败")
        if output_dir is not None:
            failure_path = output_dir / "base-reference-data-error.json"
            failure_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "error",
                        "product_code": args.product_code.strip().upper(),
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
