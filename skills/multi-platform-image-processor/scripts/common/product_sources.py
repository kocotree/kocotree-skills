from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .nas_paths import require_accessible_directory, to_unc_path
from .product_info_reader import (
    DEFAULT_ALIASES,
    extract_chinese_material,
    extract_representative_color,
    find_product_info,
)
from .product_matcher import normalize_identity
from .settings import config_root, load_json_config

logger = logging.getLogger(__name__)


@dataclass
class ProductData:
    """保存单次任务合并后的字段、字段来源和选中记录。"""

    data: dict[str, str] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)

    def get(self, name: str, default: str = "") -> str:
        """返回规范字段值。"""
        return self.data.get(name, default)

    def to_report(self) -> dict[str, Any]:
        """返回唯一内部报告中的产品资料及来源。"""
        return {"字段": self.data, "字段来源": self.sources, "选中记录": self.records}


def _clean_value(name: str, value: object) -> str:
    """将空白和占位符视为缺失，材质保留完整中文原文。"""
    text = str(value or "").strip()
    if text in {"", "/", "／", "-", "—"}:
        return ""
    return extract_chinese_material(text) if name == "中文面料" else text


def _merge(product: ProductData, values: dict[str, Any], source: dict[str, Any]) -> None:
    """仅补充已有资料中缺失的字段，并保留字段来源。"""
    for name, raw in values.items():
        if name not in DEFAULT_ALIASES:
            continue
        value = _clean_value(name, raw)
        if value and not product.get(name):
            product.data[name] = value
            product.sources[name] = source
    # 先固定高优先级资料的代表颜色，避免被 NAS 的另一规格替换。
    if not product.get("颜色"):
        color = extract_representative_color(product.data)
        if color:
            product.data["颜色"] = color
            product.sources["颜色"] = product.sources["规格"]


def _read_table(
    config: dict[str, Any],
    table: dict[str, Any],
    product_code: str,
    directory: Path,
) -> list[dict[str, Any]]:
    """使用用户身份只读查询单个产品的多维表记录。

    参数：
        config：多维表连接配置。
        table：目标表及规范字段映射。
        product_code：查询货号，查询后进行精确复核。
        directory：本次查询的临时目录。
    返回值：
        货号精确匹配的规范字段记录，附带原记录 ID。
    """
    executable = shutil.which("lark-cli")
    if not executable:
        raise RuntimeError("需要安装 lark-cli 并完成用户身份授权后读取多维表")
    table_id = table["table_id"]
    fields = table["fields"]
    query = directory / f"{table_id}-filter.json"
    query.write_text(json.dumps({"logic": "and", "conditions": [
        [fields["产品货号"], "intersects", product_code]
    ]}, ensure_ascii=False), encoding="utf-8")
    output = directory / f"{table_id}.ndjson"
    command = [executable, "base", "+record-list", "--as", "user",
               "--base-token", config["base_token"], "--table-id", table_id,
               "--filter-json", f"@{query.name}", "--output", output.name,
               "--minimal-stdout"]
    for name in fields.values():
        command.extend(["--field-id", name])
    logger.info("读取多维表 table=%s code=%s", table["name"], product_code)
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True,
                            encoding="utf-8", timeout=60)
    if result.returncode:
        raise RuntimeError(f"多维表读取失败（{table['name']}），请检查 lark-cli 用户授权与访问权限："
                           f"{result.stderr.strip() or result.stdout.strip()}")
    manifest = json.loads(result.stdout)
    if manifest["has_more"]:
        raise RuntimeError(f"单个货号在{table['name']}的记录超过查询上限，需缩小查询范围")
    records = []
    with output.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if normalize_identity(row.get(fields["产品货号"])) != normalize_identity(product_code):
                continue
            records.append({"record_id": row["record_id"], **{
                name: _clean_value(name, row.get(remote)) for name, remote in fields.items()
            }})
    logger.info("多维表读取完成 table=%s records=%d", table["name"], len(records))
    return records


def resolve_product_data(
    product_code: str,
    product_name: str,
    nas_root: Path,
    config_path: Path | None = None,
) -> ProductData:
    """按码表、款表、NAS 的优先级选择记录并补齐任务资料。

    参数：
        product_code：精确匹配的产品货号。
        product_name：可选名称，用于同货号记录的优先选择。
        nas_root：缺失字段的 Excel 补充目录，资料齐全时不访问。
        config_path：可替换的多维表连接与字段映射配置。
    返回值：
        供整次任务共用的产品字段和来源；查询失败或必要字段缺失时抛出异常。
    """
    config = load_json_config(config_path or config_root() / "product_sources.json")
    product = ProductData()
    logger.info("开始解析产品资料 code=%s", product_code)
    with TemporaryDirectory(prefix="kocotree-product-data-") as temp:
        for table in config["tables"]:
            rows = _read_table(config, table, product_code, Path(temp))
            if not rows:
                continue
            # 每表只选一条记录，优先名称相符、资料完整的记录，随后按 ID 稳定排序。
            selected = min(rows, key=lambda row: (
                bool(product_name) and normalize_identity(row.get("产品名称")) != normalize_identity(product_name),
                -sum(bool(row.get(name)) for name in table["fields"]), row["record_id"],
            ))
            source = {"来源": table["name"], "表ID": table["table_id"],
                      "记录ID": selected["record_id"], "Base": config["base_token"]}
            product.records.append(source)
            _merge(product, {k: v for k, v in selected.items() if k != "record_id"}, source)
            logger.info("选定多维表记录 table=%s record=%s candidates=%d",
                        table["name"], selected["record_id"], len(rows))
    required = ("产品货号", "产品名称", "中文面料", "颜色")
    missing = [name for name in required if not product.get(name)]
    if missing:
        logger.info("从 NAS 补充产品资料 fields=%s", "、".join(missing))
        root = require_accessible_directory(to_unc_path(nas_root), "产品信息目录")
        # 货号是补充资料的依据，NAS 名称差异不覆盖多维表的正式名称。
        match = find_product_info(root, product_code)
        if match.selected:
            record = match.selected
            source = {"来源": "NAS Excel", "文件": str(record.file),
                      "工作表": record.sheet, "行号": record.row}
            product.records.append(source)
            _merge(product, record.data, source)
        missing = [name for name in required if not product.get(name)]
        if missing:
            raise RuntimeError(f"产品资料缺少：{'、'.join(missing)}；{match.reason}")
    logger.info("产品资料解析完成 code=%s sources=%d", product_code, len(product.records))
    return product
