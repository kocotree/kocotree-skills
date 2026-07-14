"""通用工具：日志配置、JSON 读写、目录清理与素材收集。"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any


def setup_logging(level: int = logging.INFO) -> None:
    """配置全局日志输出格式。

    参数:
        level: 日志级别，默认 INFO。
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器。

    参数:
        name: 日志器名称，一般传模块的 __name__。
    返回:
        对应的 logging.Logger 实例。
    """
    return logging.getLogger(name)


def write_json(path: Path, data: Any) -> None:
    """以 UTF-8、缩进格式把数据写入 JSON 文件，自动创建父目录。

    参数:
        path: 输出文件路径。
        data: 可被 json 序列化的数据。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    """读取并解析 JSON 文件。

    参数:
        path: JSON 文件路径。
    返回:
        解析后的数据。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def clear_directory(path: Path, keep: set[Path] | None = None) -> None:
    """清空目录内容但保留目录本身，目录不存在时创建。

    参数:
        path: 需要清空的目录。
        keep: 需要保留的文件/子目录绝对路径集合（如标注清单），不被删除。
    """
    path.mkdir(parents=True, exist_ok=True)
    keep_resolved = {p.resolve() for p in keep} if keep else set()
    for child in path.iterdir():
        if child.resolve() in keep_resolved:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def collect_images(directory: Path, suffixes: set[str]) -> dict[str, Path]:
    """收集目录下指定后缀的图片，按颜色名归集。

    参数:
        directory: 图片所在目录（如 模特图/、透明图/）。
        suffixes: 允许的扩展名集合，小写且含点，如 {".jpg", ".png"}。
    返回:
        {颜色名(文件名去扩展名): 图片路径}；目录不存在返回空字典。
    """
    if not directory.exists():
        return {}
    return {
        path.stem: path
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in suffixes
    }
