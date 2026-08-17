#!/usr/bin/env python3
"""按容量上限清理质检工作目录。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Iterable


LOGGER = logging.getLogger("source_pack_work_cleanup")
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORK_DIR = SCRIPT_DIR / "work"
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "work-config.json"


def is_directory_junction(path: Path) -> bool:
    """判断路径是否为 Windows 目录联接。

    参数：
        path: 需要判断的路径。

    返回值：
        路径为目录联接时返回 True，否则返回 False。
    """

    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


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


def load_max_size_mb(config_path: Path = DEFAULT_CONFIG_PATH) -> float:
    """读取工作目录容量上限。

    参数：
        config_path: 工作目录配置文件路径。

    返回值：
        大于零的容量上限，单位为 MiB。
    """

    data = json.loads(config_path.read_text(encoding="utf-8"))
    max_size_mb = float(data["max_size_mb"])
    if max_size_mb <= 0:
        raise ValueError("max_size_mb 必须大于零")
    return max_size_mb


def measure_path(path: Path) -> tuple[int, float]:
    """计算文件或目录大小及最近修改时间，不跟随符号链接。

    参数：
        path: 需要测量的文件、目录或符号链接。

    返回值：
        文件总字节数和最近修改时间戳。
    """

    stat = path.lstat()
    if path.is_symlink() or is_directory_junction(path) or not path.is_dir():
        return stat.st_size, stat.st_mtime

    total_size = 0
    latest_mtime = stat.st_mtime
    try:
        entries = list(os.scandir(path))
    except OSError as exc:
        LOGGER.warning("工作目录项读取失败：%s；原因：%s", path, exc)
        return total_size, latest_mtime

    for entry in entries:
        child = Path(entry.path)
        try:
            child_size, child_mtime = measure_path(child)
        except OSError as exc:
            LOGGER.warning("工作目录项测量失败：%s；原因：%s", child, exc)
            continue
        total_size += child_size
        latest_mtime = max(latest_mtime, child_mtime)
    return total_size, latest_mtime


def is_protected(candidate: Path, protected_paths: Iterable[Path]) -> bool:
    """判断顶层任务项是否包含受保护路径。

    参数：
        candidate: `work` 下的顶层任务项。
        protected_paths: 当前运行需要保留的路径集合。

    返回值：
        包含受保护路径时返回 True，否则返回 False。
    """

    candidate_resolved = candidate.resolve(strict=False)
    for protected_path in protected_paths:
        protected_resolved = protected_path.resolve(strict=False)
        if protected_resolved == candidate_resolved:
            return True
        if candidate_resolved in protected_resolved.parents:
            return True
    return False


def remove_work_item(path: Path, work_dir: Path) -> None:
    """删除 `work` 下的单个顶层任务项。

    参数：
        path: 需要删除的顶层任务文件或目录。
        work_dir: 工作目录根路径。

    返回值：
        无。
    """

    resolved_work_dir = work_dir.resolve()
    if path.parent.resolve() != resolved_work_dir or path.resolve(strict=False) == resolved_work_dir:
        raise ValueError(f"拒绝清理工作目录范围外的路径：{path}")
    if is_directory_junction(path):
        path.rmdir()
    elif path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def cleanup_work_directory(
    work_dir: Path = DEFAULT_WORK_DIR,
    max_size_mb: float | None = None,
    protected_paths: Iterable[Path] = (),
    dry_run: bool = False,
) -> dict[str, object]:
    """按最后修改时间清理最旧任务，直到工作目录不超过容量上限。

    参数：
        work_dir: 存放质检运行产物的工作目录。
        max_size_mb: 容量上限，单位为 MiB；为 None 时读取配置文件。
        protected_paths: 当前运行必须保留的文件或目录。
        dry_run: 为 True 时只计算计划，不执行删除。

    返回值：
        包含清理前后容量、删除项和是否仍超限的汇总字典。
    """

    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    effective_max_mb = load_max_size_mb() if max_size_mb is None else max_size_mb
    if effective_max_mb <= 0:
        raise ValueError("max_size_mb 必须大于零")
    limit_bytes = int(effective_max_mb * 1024 * 1024)

    items: list[dict[str, object]] = []
    for path in work_dir.iterdir():
        size, modified_time = measure_path(path)
        items.append(
            {
                "path": path,
                "size": size,
                "modified_time": modified_time,
                "protected": is_protected(path, protected_paths),
            }
        )

    before_bytes = sum(int(item["size"]) for item in items)
    projected_bytes = before_bytes
    removed: list[dict[str, object]] = []
    if before_bytes > limit_bytes:
        LOGGER.warning(
            "工作目录超过容量上限：当前=%.2f MiB，上限=%.2f MiB",
            before_bytes / 1024 / 1024,
            effective_max_mb,
        )
        for item in sorted(
            items,
            key=lambda value: (
                float(value["modified_time"]),
                str(value["path"]).casefold(),
            ),
        ):
            if projected_bytes <= limit_bytes:
                break
            if bool(item["protected"]):
                continue
            path = Path(item["path"])
            size = int(item["size"])
            if not dry_run:
                remove_work_item(path, work_dir)
            projected_bytes -= size
            removed.append({"path": str(path), "bytes": size})
            action = "计划清理" if dry_run else "已清理"
            LOGGER.warning("%s旧任务：%s；释放=%.2f MiB", action, path, size / 1024 / 1024)

    over_limit = projected_bytes > limit_bytes
    if over_limit:
        LOGGER.warning("受保护任务占用使工作目录仍高于容量上限")
    elif dry_run and removed:
        LOGGER.info("清理后预计占用：%.2f MiB", projected_bytes / 1024 / 1024)
    else:
        LOGGER.info("工作目录容量正常：%.2f MiB", projected_bytes / 1024 / 1024)
    return {
        "work_dir": str(work_dir),
        "max_size_mb": effective_max_mb,
        "before_bytes": before_bytes,
        "after_bytes": projected_bytes,
        "removed": removed,
        "over_limit": over_limit,
        "dry_run": dry_run,
    }


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数：
        无。

    返回值：
        包含工作目录、容量上限、预演状态和日志级别的参数对象。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR, help="工作目录")
    parser.add_argument("--max-size-mb", type=float, help="容量上限，单位为 MiB")
    parser.add_argument("--dry-run", action="store_true", help="只显示清理计划")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    return parser.parse_args()


def main() -> int:
    """执行工作目录容量检查和清理。

    参数：
        无，参数从命令行读取。

    返回值：
        执行成功返回 0；配置、扫描或清理失败返回 1。
    """

    args = parse_args()
    configure_logging(args.log_level)
    try:
        cleanup_work_directory(
            work_dir=args.work_dir,
            max_size_mb=args.max_size_mb,
            dry_run=args.dry_run,
        )
    except Exception:
        LOGGER.exception("工作目录清理失败")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
