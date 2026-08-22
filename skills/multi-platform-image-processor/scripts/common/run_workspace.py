from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

MAX_INTERNAL_OUTPUT_BYTES = 1024**3
TEXT_REMOVAL_CANDIDATES_ENV = "KOCOTREE_TEXT_REMOVAL_CANDIDATES"


@dataclass(frozen=True)
class RunWorkspace:
    """保存单次产品处理使用的内部路径。

    参数：
        run_id：单次运行的唯一标识。
        timestamp：交付目录使用的时间戳。
        root：本次运行的内部根目录。
        staging_root：六平台成品发布前的暂存根目录。
        report_path：内部完整报告路径。
        log_path：内部运行日志路径。
        candidates_dir：站外 SKU 去字候选图目录。
    返回值：
        该数据类实例提供本次运行的全部内部路径。
    """

    run_id: str
    timestamp: str
    root: Path
    staging_root: Path
    report_path: Path
    log_path: Path
    candidates_dir: Path


def internal_runs_root() -> Path:
    """返回 Skill 内部运行目录。"""
    return Path(__file__).resolve().parents[1] / "output" / "runs"


def create_run_workspace(product_code: str, timestamp: str | None = None) -> RunWorkspace:
    """创建单次产品处理的内部工作目录。

    参数：
        product_code：用于标识运行目录的产品货号。
        timestamp：可选的固定时间戳，未提供时使用当前时间。
    返回值：
        已创建的内部运行工作区。
    """
    run_timestamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_code = (
        "".join(character for character in product_code if character.isalnum())
        or "product"
    )
    base_id = f"{run_timestamp}-{safe_code}"
    runs_root = internal_runs_root()
    run_id = base_id
    suffix = 2
    while (runs_root / run_id).exists():
        run_id = f"{base_id}-{suffix}"
        suffix += 1
    root = runs_root / run_id
    staging_root = root / "staging"
    candidates_dir = root / "candidates"
    staging_root.mkdir(parents=True, exist_ok=False)
    candidates_dir.mkdir(parents=True, exist_ok=False)
    logger.info("内部运行目录已创建 run_id=%s root=%r", run_id, str(root))
    return RunWorkspace(
        run_id=run_id,
        timestamp=run_timestamp,
        root=root,
        staging_root=staging_root,
        report_path=root / "report.json",
        log_path=root / "run.log",
        candidates_dir=candidates_dir,
    )


def publish_delivery(staging_product: Path, output_root: Path) -> Path:
    """将通过处理的暂存产品包发布为唯一用户交付目录。

    参数：
        staging_product：内部暂存区中的完整产品目录。
        output_root：用户指定的最终输出根目录。
    返回值：
        已发布的最终产品目录。
    """
    if not staging_product.is_dir():
        raise RuntimeError(f"内部暂存产品目录不存在：{staging_product}")
    output_root.mkdir(parents=True, exist_ok=True)
    delivery = output_root / staging_product.name
    if delivery.exists():
        raise RuntimeError(f"最终交付目录已存在：{delivery}")
    publishing = output_root / f".{staging_product.name}.publishing"
    if publishing.exists():
        raise RuntimeError(f"存在未确认的发布临时目录：{publishing}")
    try:
        logger.info(
            "产品交付目录开始发布 staging=%r output=%r",
            str(staging_product),
            str(delivery),
        )
        shutil.copytree(staging_product, publishing)
        publishing.replace(delivery)
    except Exception:
        if publishing.exists():
            shutil.rmtree(publishing)
        raise
    shutil.rmtree(staging_product.parent)
    logger.info("产品交付目录发布完成 output=%r", str(delivery))
    return delivery


def replace_report_path_prefix(value: Any, source: Path, target: Path) -> Any:
    """将报告中的暂存路径前缀替换为最终交付路径。

    参数：
        value：报告对象或其中的任意节点。
        source：需要替换的暂存产品目录。
        target：发布后的最终产品目录。
    返回值：
        路径前缀完成替换的报告节点。
    """
    if isinstance(value, dict):
        return {
            key: replace_report_path_prefix(item, source, target)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_report_path_prefix(item, source, target) for item in value]
    if isinstance(value, str):
        source_text = str(source)
        if (
            value == source_text
            or value.startswith(source_text + "\\")
            or value.startswith(source_text + "/")
        ):
            return str(target) + value[len(source_text) :]
    return value


def _directory_size(path: Path) -> int:
    """计算目录内普通文件的总字节数。"""
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                logger.warning("内部文件大小读取失败 path=%r", str(item))
    return total


def prune_internal_runs(
    runs_root: Path | None = None,
    max_bytes: int = MAX_INTERNAL_OUTPUT_BYTES,
    protected: Path | None = None,
) -> list[Path]:
    """按容量删除最旧的完整内部运行目录。

    参数：
        runs_root：内部运行根目录，未提供时使用 Skill 默认目录。
        max_bytes：内部运行产物允许占用的最大字节数。
        protected：本轮仍在使用、不可删除的运行目录。
    返回值：
        本次删除的完整运行目录列表。
    """
    root = runs_root or internal_runs_root()
    if not root.is_dir():
        return []
    run_dirs = [path for path in root.iterdir() if path.is_dir()]
    sizes = {path: _directory_size(path) for path in run_dirs}
    total = sum(sizes.values())
    protected_resolved = protected.resolve() if protected else None
    oldest_first = sorted(run_dirs, key=lambda path: (path.stat().st_mtime, path.name))
    removed: list[Path] = []
    for run_dir in oldest_first:
        if total <= max_bytes:
            break
        if protected_resolved is not None and run_dir.resolve() == protected_resolved:
            continue
        try:
            shutil.rmtree(run_dir)
        except OSError as exc:
            logger.warning("内部旧运行清理失败 run=%r error=%s", str(run_dir), exc)
            continue
        total -= sizes[run_dir]
        removed.append(run_dir)
        logger.info("内部旧运行已清理 run=%r remaining_bytes=%d", str(run_dir), total)
    if total > max_bytes:
        logger.warning("内部运行目录仍超过容量上限 bytes=%d limit=%d", total, max_bytes)
    return removed
