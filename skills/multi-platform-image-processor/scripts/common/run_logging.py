from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock


日志格式 = (
    "%(asctime)s %(levelname)s "
    "run_id=%(run_id)s product=%(product)s platform=%(platform)s "
    "stage=%(stage)s event=%(event)s status=%(status)s "
    "%(name)s - %(message)s"
)

_处理器锁 = Lock()
_当前文件处理器: logging.FileHandler | None = None


class 运行上下文过滤器(logging.Filter):
    """为运行日志补充统一上下文字段。"""

    def __init__(self, run_id: str, product: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.product = product

    def filter(self, record: logging.LogRecord) -> bool:
        """补全日志记录中的运行、产品、平台和处理阶段字段。"""
        defaults = {
            "run_id": self.run_id,
            "product": self.product or "-",
            "platform": "-",
            "stage": "-",
            "event": "-",
            "status": "-",
        }
        for key, value in defaults.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def report_artifact_prefix(path: Path) -> str:
    """根据主报告文件名生成同一次运行的产物前缀。"""
    stem = path.stem
    return stem.removesuffix("-report")


def configure_run_file_logging(log_path: Path, run_id: str, product: str) -> Path:
    """配置本次处理使用的独立文件日志。

    功能说明：关闭上一份运行日志处理器，为当前产品创建 UTF-8 日志文件，
    并向所有标准 logging 日志补充统一上下文字段。

    参数：
        log_path：日志文件保存路径。
        run_id：本次运行的唯一标识。
        product：当前处理的产品名称。
    返回值：
        已创建的日志文件绝对路径。
    """
    global _当前文件处理器
    resolved_path = log_path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    with _处理器锁:
        if _当前文件处理器 is not None:
            root_logger.removeHandler(_当前文件处理器)
            _当前文件处理器.close()
        handler = logging.FileHandler(resolved_path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(日志格式, datefmt="%Y-%m-%d %H:%M:%S"))
        handler.addFilter(运行上下文过滤器(run_id, product))
        root_logger.addHandler(handler)
        if root_logger.level > logging.INFO:
            root_logger.setLevel(logging.INFO)
        _当前文件处理器 = handler
    return resolved_path


def close_run_file_logging() -> None:
    """关闭当前运行日志文件处理器。"""
    global _当前文件处理器
    root_logger = logging.getLogger()
    with _处理器锁:
        if _当前文件处理器 is None:
            return
        root_logger.removeHandler(_当前文件处理器)
        _当前文件处理器.close()
        _当前文件处理器 = None
