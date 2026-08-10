from __future__ import annotations

import argparse
import logging
import sys

from auth.auth_client import ensure_token
from common.environment import configure_runtime_environment
from common.utils import 全部平台
from workflows.certificate_assets import run_certificate_workflow
from workflows.full_package import run_full_workflow
from workflows.material_correction import run_material_workflow
from workflows.platform_processing import run_platform_workflow


logger = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析统一入口的工作流与业务参数。

    参数：
        argv：命令行参数列表。
    返回值：
        已验证基础格式的命令行命名空间。
    """
    parser = argparse.ArgumentParser(description="处理多平台商品图片、合格证图片和详情页面料。")
    parser.add_argument(
        "--mode",
        default="platform",
        choices=["full", "certificate", "material", "platform"],
        help="工作流模式，默认 platform 兼容原平台处理",
    )
    parser.add_argument("--source", required=True, help="数据包、产品目录或多平台成品包")
    parser.add_argument("--output", default="", help="最终输出根目录")
    parser.add_argument("--report", default="", help="主报告 JSON 路径")
    parser.add_argument("--product-code", default="", help="产品货号")
    parser.add_argument("--product-name", default="", help="产品名称")
    parser.add_argument("--color", default="", help="代表颜色")
    parser.add_argument("--include-certificate-assets", action="store_true", help="完整流程生成固定三张业务图片")
    parser.add_argument("--include-certificate-fabric", action="store_true", help="合格证图加入 Excel 中文面料")
    parser.add_argument("--nas-root", default="", help="NAS 标准 UNC 根目录")
    parser.add_argument("--product-info-root", default="", help="产品信息 Excel 目录")
    parser.add_argument("--certificate-root", default="", help="BarTender 合格证目录")
    parser.add_argument("--material-plan", default="", help="详情页面料视觉定位计划 JSON")
    parser.add_argument("--size-table-source", default="", help="实际尺码表所在详情图")
    parser.add_argument("--size-table-box", default="", help="尺码表完整区域 left,top,right,bottom")
    parser.add_argument("--fabric-anchor", default="", help="合格证“等级”下方面料锚点 x,y")
    parser.add_argument("--visual-review-approved", action="store_true", help="标记 Agent 已完成业务图片视觉复核")
    parser.add_argument("--template", default="", help="平台模板目录")
    parser.add_argument(
        "--platform",
        default="all",
        choices=["all", *全部平台],
        help="目标平台，默认 all",
    )
    args = parser.parse_args(argv)
    if args.mode != "platform" and not args.product_code:
        parser.error(f"{args.mode} 模式必须提供 --product-code")
    return args


def main(argv: list[str] | None = None) -> int:
    """执行统一多模式入口。

    参数：
        argv：可选命令行参数；未提供时读取系统参数。
    返回值：
        工作流退出码。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.mode in {"full", "platform"}:
            configure_runtime_environment()
            ensure_token()
        runners = {
            "full": run_full_workflow,
            "certificate": run_certificate_workflow,
            "material": run_material_workflow,
            "platform": run_platform_workflow,
        }
        logger.info("统一入口开始 mode=%s source=%r", args.mode, args.source)
        code = runners[args.mode](args)
        logger.info("统一入口结束 mode=%s code=%d", args.mode, code)
        return code
    except Exception as exc:
        logger.error("工作流启动失败 mode=%s error=%s", args.mode, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
