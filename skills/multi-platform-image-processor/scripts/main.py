from __future__ import annotations

import argparse
import logging
import sys

from auth.auth_client import ensure_token
from common.environment import configure_runtime_environment
from workflows.full_package import run_full_workflow

logger = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析完整处理流程的命令行参数。

    参数：
        argv：命令行参数列表。
    返回值：
        已验证基础格式的命令行命名空间。
    """
    parser = argparse.ArgumentParser(description="处理产品数据包并输出完整多平台图片成品包。")
    parser.add_argument("--source", required=True, help="产品目录或其中的数据包目录")
    parser.add_argument("--output", default="", help="最终输出根目录")
    parser.add_argument("--product-code", default="", help="产品货号；目录可可靠识别时可省略")
    parser.add_argument("--product-name", default="", help="产品名称；用于同货号候选复核")
    parser.add_argument("--material-plan", default="", help=argparse.SUPPRESS)
    parser.add_argument("--detail-plan", default="", help=argparse.SUPPRESS)
    parser.add_argument("--size-table-source", default="", help=argparse.SUPPRESS)
    parser.add_argument("--size-table-box", default="", help=argparse.SUPPRESS)
    parser.add_argument("--visual-review-approved", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行固定的完整产品图片处理流程。

    参数：
        argv：可选命令行参数；未提供时读取系统参数。
    返回值：
        工作流退出码。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args(argv or sys.argv[1:])
    try:
        configure_runtime_environment()
        ensure_token()
        logger.info("完整处理流程开始 source=%r", args.source)
        code = run_full_workflow(args)
        logger.info("完整处理流程结束 code=%d", code)
        return code
    except Exception as exc:
        logger.error("完整处理流程启动失败 error=%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
