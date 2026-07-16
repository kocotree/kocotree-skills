"""批次输出保留策略。"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.utils import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_BATCHES = 50
_CURRENT_BATCH_PATTERN = re.compile(r"^(?P<timestamp>\d{8}-\d{6})_.+$")
_LEGACY_BATCH_PATTERN = re.compile(r"^.+_(?P<timestamp>\d{8}-\d{6})$")


def _batch_timestamp(path: Path) -> datetime | None:
    """从新旧批次目录名中解析时间戳。"""
    match = _CURRENT_BATCH_PATTERN.match(path.name) or _LEGACY_BATCH_PATTERN.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("timestamp"), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def enforce_batch_retention(
    output_base: Path,
    max_batches: int = DEFAULT_MAX_BATCHES,
    protected_batch: Path | None = None,
) -> dict[str, Any]:
    """限制 output 中保留的批次数量并删除最早批次。

    参数:
        output_base: 固定批次输出根目录。
        max_batches: 最多保留的批次数量。
        protected_batch: 本轮新建批次目录，不参与删除。
    返回值:
        清理前后数量、上限和已删除目录列表。
    """
    if max_batches < 1:
        raise ValueError("max_batches 必须大于 0")
    base = output_base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    protected = protected_batch.resolve() if protected_batch else None
    batches: list[tuple[datetime, Path]] = []
    for path in base.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        timestamp = _batch_timestamp(path)
        if timestamp is not None:
            batches.append((timestamp, path.resolve()))

    before = len(batches)
    removable = sorted(
        (item for item in batches if item[1] != protected),
        key=lambda item: (item[0], item[1].name),
    )
    removed: list[str] = []
    while before - len(removed) > max_batches:
        if not removable:
            raise RuntimeError("批次数量超过上限，但没有可安全删除的批次")
        _, target = removable.pop(0)
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise RuntimeError(f"拒绝删除 output 目录以外的路径: {target}") from exc
        logger.info("批次数量超过 %d，删除最早批次: %s", max_batches, target)
        shutil.rmtree(target)
        removed.append(str(target))

    report = {
        "max_batches": max_batches,
        "before": before,
        "after": before - len(removed),
        "removed": removed,
    }
    logger.info("批次保留检查完成: %s", report)
    return report
