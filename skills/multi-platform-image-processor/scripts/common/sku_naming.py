"""规格图片的输出文件名处理。"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)
_PREFIX = re.compile(r"^\s*(?:\d+(?:[\s_、-]+|[.．](?!\d))|\(\d+\)|（\d+）|\[\d+\]|【\d+】)[\s_.、．-]*")


def sku_output_path(path: Path, used: set[Path]) -> Path:
    """清理规格图片的排序前缀，并分配本轮唯一输出路径。

    参数：
        path：已确定输出目录与图片后缀的目标路径。
        used：本轮已分配路径集合，分配成功后写入此集合。
    返回值：
        保留目录、清理前缀且以序号区分重名的图片路径。
    """
    cleaned = _PREFIX.sub("", path.stem, count=1)
    # 纯数字及清理后为空的名称保留，避免丢失唯一识别信息。
    if cleaned and not path.stem.strip().isdigit():
        target = path.with_name(cleaned + path.suffix)
    else:
        target = path
    candidate = target
    index = 2
    while candidate in used:
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        index += 1
    used.add(candidate)
    if candidate != path:
        logger.info("规格图片输出命名 original=%r output=%r", str(path), str(candidate))
    return candidate
