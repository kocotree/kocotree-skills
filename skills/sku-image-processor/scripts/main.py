"""命令行入口：服装 SKU 图片工作流，提供 prep / annotate / validate-annotation / render / review。

主流程：
1. prep —— 扫描素材、生成 annotations.json、模板参考线、坐标网格和 YOLO 骨架辅助图。
2. annotate —— 生成标注任务摘要，由 agent 或视觉模型填写视觉标注。
3. validate-annotation —— 校验标注格式与渲染前几何风险。
4. render —— 按标注合成、验收并输出交付件与报告。
5. review —— 汇总 render 失败项，生成复查清单。
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from annotation.check import validate_annotations
from annotation.review import build_review_report
from annotation.tasks import build_annotation_tasks
from core.output_layout import layout_from_annotations
from core.utils import setup_logging
from pipeline.prep import run_prep
from pipeline.render import run_render

SCRIPTS_DIR = Path(__file__).resolve().parent
# skill 根目录（scripts 的上一级），用于定位自带模板与字体
SKILL_ROOT = SCRIPTS_DIR.parent
DEFAULT_FONT = SKILL_ROOT / "assets" / "方正兰亭中黑_GBK-Regular.ttf"
DEFAULT_TEMPLATE = SKILL_ROOT / "template" / "模板.png"
# 批次输出根目录：scripts/output/<输入目录名>_<时间戳>/
DEFAULT_OUTPUT_BASE = SCRIPTS_DIR / "output"


def _resolve_template(input_root: Path, template_file: Path) -> Path:
    """解析实际使用的模板路径：input_root/模板.png 优先，否则用传入模板。

    参数:
        input_root: 素材根目录。
        template_file: 命令行传入或默认的模板路径。
    返回:
        实际模板路径。
    """
    input_template = input_root / "模板.png"
    return input_template if input_template.exists() else template_file


def _resolve_output_annotations(annotations_path: Path) -> Path:
    """校验 annotations.json 位于固定输出目录 scripts/output 下。

    参数:
        annotations_path: 命令行传入的标注清单路径。
    返回:
        解析后的 annotations.json 绝对路径。
    """
    resolved = annotations_path.resolve()
    output_base = DEFAULT_OUTPUT_BASE.resolve()
    if resolved.name != "annotations.json":
        raise SystemExit("annotations 参数必须指向 scripts/output/<批次>/annotations.json")
    try:
        resolved.relative_to(output_base)
    except ValueError as exc:
        raise SystemExit("输出目录固定为 scripts/output，请使用该目录下的 annotations.json") from exc
    return resolved


def parse_args() -> argparse.Namespace:
    """解析命令行参数（含完整五段流程子命令）。"""
    parser = argparse.ArgumentParser(description="生成服装 SKU 交付图片。")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prep", help="扫描素材，生成标注清单、模板参考线、网格图和 YOLO 骨架图")
    prep.add_argument("--input-root", type=Path, required=True, help="素材目录，可为总目录或单商品目录")
    prep.add_argument("--template-file", type=Path, default=DEFAULT_TEMPLATE, help="SKU 模板 PNG，缺省用自带模板")
    prep.add_argument("--pose-model-name", default="models/yolo11n-pose.pt", help="YOLO pose 权重名或本地权重路径")
    prep.add_argument("--pose-confidence", type=float, default=0.25, help="YOLO 人体检测置信度阈值")
    prep.add_argument("--skip-pose", action="store_true", help="仅在调试依赖问题时跳过 YOLO 骨架辅助")

    annotate = sub.add_parser("annotate", help="生成 agent/视觉模型使用的标注任务摘要")
    annotate.add_argument("--annotations", type=Path, required=True, help="prep 生成的 annotations.json")

    validate = sub.add_parser("validate-annotation", help="校验已填写的 annotations.json")
    validate.add_argument("--annotations", type=Path, required=True, help="待校验的 annotations.json")

    render = sub.add_parser("render", help="按标注清单合成、验收并输出交付件")
    render.add_argument("--input-root", type=Path, required=True, help="素材目录，可为总目录或单商品目录")
    render.add_argument("--annotations", type=Path, required=True, help="prep 生成、agent 填好的 annotations.json")
    render.add_argument("--template-file", type=Path, default=DEFAULT_TEMPLATE, help="SKU 模板 PNG，缺省用自带模板")
    render.add_argument("--font-file", type=Path, default=DEFAULT_FONT, help="颜色名标签字体，缺省用自带字体")

    review = sub.add_parser("review", help="根据 summary.json 生成失败复查摘要")
    review.add_argument("--annotations", type=Path, required=True, help="批次 annotations.json")
    return parser.parse_args()


def main() -> None:
    """程序入口：配置日志，按五段工作流子命令分发。"""
    setup_logging()
    args = parse_args()

    if args.command == "prep":
        template_path = _resolve_template(args.input_root, args.template_file)
        # 批次目录固定在 scripts/output/<输入目录名>_<时间戳>/
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        batch_root = DEFAULT_OUTPUT_BASE / f"{args.input_root.name}_{timestamp}"
        run_prep(
            input_root=args.input_root,
            batch_root=batch_root,
            template_path=template_path,
            pose_model_name=args.pose_model_name,
            pose_confidence=args.pose_confidence,
            skip_pose=args.skip_pose,
        )
        print(f"prep 完成，标注清单: {batch_root / 'annotations.json'}")
        print("下一步运行 annotate 生成标注任务摘要，填写后运行 validate-annotation。")
        return

    if args.command == "annotate":
        annotations_path = _resolve_output_annotations(args.annotations)
        report = build_annotation_tasks(annotations_path)
        print(f"annotate 任务摘要完成: {report['task_count']} 项")
        print(f"请查看 summary.json 与 annotated/ 图片后填写 annotations.json")
        return

    if args.command == "validate-annotation":
        annotations_path = _resolve_output_annotations(args.annotations)
        report = validate_annotations(annotations_path)
        print(f"validate-annotation 完成: {report['summary']}")
        return

    if args.command == "review":
        annotations_path = _resolve_output_annotations(args.annotations)
        report = build_review_report(annotations_path)
        print(f"review 完成: {report['summary']}")
        return

    # 输出结构由 annotations.json 所在批次目录锁定
    annotations_path = _resolve_output_annotations(args.annotations)
    template_path = _resolve_template(args.input_root, args.template_file)
    layout = layout_from_annotations(annotations_path)
    report = run_render(
        input_root=args.input_root,
        output_root=layout.final_dir,
        qa_root=layout.batch_root,
        font_path=args.font_file,
        annotations_path=annotations_path,
        template_path=template_path,
    )
    print(f"render 完成: {report['summary']}")
    print(f"成品图目录: {layout.final_dir}")
    if report.get("contact_sheet"):
        print(f"完整示例图: {report['contact_sheet']}")
    print(f"批次目录: {layout.batch_root}")


if __name__ == "__main__":
    main()
