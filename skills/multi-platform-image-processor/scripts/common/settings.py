from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BusinessPaths:
    """保存业务资料目录。

    参数：
        nas_root：NAS 的标准 UNC 根目录。
        product_info_root：产品信息表目录。
        certificate_root：BarTender 合格证目录。
    返回值：
        该数据类实例可供工作流读取三个已解析路径。
    """

    nas_root: Path
    product_info_root: Path
    certificate_root: Path


def skill_root() -> Path:
    """返回当前 Skill 根目录。"""
    return Path(__file__).resolve().parents[2]


def config_root() -> Path:
    """返回脚本配置目录。"""
    return Path(__file__).resolve().parents[1] / "config"


def load_json_config(path: Path) -> dict[str, Any]:
    """读取 UTF-8 JSON 配置。

    参数：
        path：配置文件路径。
    返回值：
        配置对象。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"配置文件无法读取：{path}，{exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"配置文件根节点必须是对象：{path}")
    return data


def resolve_business_paths(
    config_path: Path | None = None,
) -> BusinessPaths:
    """按环境变量和配置文件解析业务路径。

    参数：
        config_path：可选的业务路径配置文件。
    返回值：
        解析完成的业务路径集合。
    """
    path = config_path or config_root() / "business_paths.json"
    config = load_json_config(path)
    root_value = (
        os.environ.get("KOCOTREE_NAS_ROOT", "")
        or str(config.get("NAS根目录", ""))
    ).strip()
    if not root_value:
        raise RuntimeError("NAS 根目录未配置")

    root = Path(root_value)
    product_value = os.environ.get("KOCOTREE_PRODUCT_INFO_ROOT", "").strip()
    certificate_value = os.environ.get("KOCOTREE_CERTIFICATE_ROOT", "").strip()
    product_path = (
        Path(product_value)
        if product_value
        else root / str(config.get("产品信息相对目录", ""))
    )
    certificate_path = (
        Path(certificate_value)
        if certificate_value
        else root / str(config.get("合格证相对目录", ""))
    )
    logger.info(
        "业务路径解析完成 nas=%r product_info=%r certificate=%r",
        str(root),
        str(product_path),
        str(certificate_path),
    )
    return BusinessPaths(root, product_path, certificate_path)
