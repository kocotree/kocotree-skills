from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from uuid import uuid4

from .utils import ensure_dir, add_failure, add_risk
from .image_resize_compress import fit_into_canvas, open_image, save_jpg_under
from .sku_card_crop import (
    CardCropError,
    build_model_input,
    composite_editable_regions,
    detect_right_card_plan,
    normalize_model_output,
    validate_protected_regions,
)

DEFAULT_TEXT2IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_TEXT2IMAGE_TIMEOUT = 300
TEXT2IMAGE_GITHUB_ZIP_URL = "https://github.com/ranjingya/kocotree-skills/archive/refs/heads/master.zip"
TEXT2IMAGE_GITHUB_SKILL_PATH = Path("skills") / "text2image"
TEMP_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_REMOVAL_PROMPT = "Edit only the existing text inside the colored decorative label on the right-side product card. Remove the label text and fill only the removed character strokes with the surrounding original label background. Keep the input aspect ratio, composition, card position, label color, gradient, texture, outline, rounded corners, curved edges, shadows, product image, hand, background, canvas edges, and image corners unchanged. Do not create, remove, move, resize, recolor, or redraw any block, border, label, object, logo, symbol, number, or decoration. Do not modify text or logos printed on the product itself. If no removable label text is present or the target is uncertain, return the input unchanged."

logger = logging.getLogger(__name__)


# ── Path helpers ──────────────────────────────────────────────

def _venv_python(script_dir: Path) -> Path:
    if sys.platform == "win32":
        return script_dir / ".venv" / "Scripts" / "python.exe"
    return script_dir / ".venv" / "bin" / "python"


def _current_skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".codex"


# ── Skill validation ─────────────────────────────────────────

def _read_skill_name(path: Path) -> str:
    try:
        for line in (path / "SKILL.md").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("name:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""


def _is_valid_skill(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "SKILL.md").exists()
        and (path / "scripts" / "main.py").exists()
        and _read_skill_name(path) == "text2image"
    )


# ── venv management ──────────────────────────────────────────

def _uv_sync(script_dir: Path) -> tuple[bool, str]:
    uv = shutil.which("uv")
    if not uv:
        return False, "uv 未安装，请先安装 uv 后重试"
    try:
        result = subprocess.run(
            [uv, "sync"],
            cwd=script_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as exc:
        return False, f"uv sync 执行失败：{exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, f"uv sync 失败：{detail[:500]}"
    return True, "uv sync 完成"


def _ensure_venv(script_dir: Path) -> None:
    if _venv_python(script_dir).exists():
        return
    ok, msg = _uv_sync(script_dir)
    if ok:
        print(f"text2image 依赖已自动安装：{script_dir}", flush=True)
    else:
        print(f"text2image 依赖自动安装失败：{msg}", flush=True)


# ── Skill discovery & install ────────────────────────────────

def _find_local_candidates() -> list[Path]:
    skills_root = _codex_home() / "skills"
    candidates: list[Path] = [skills_root / "text2image"]
    if skills_root.exists():
        try:
            candidates.extend(p for p in skills_root.rglob("text2image") if p.is_dir())
            candidates.extend(
                m.parent for m in skills_root.rglob("SKILL.md")
                if _read_skill_name(m.parent) == "text2image"
            )
        except OSError:
            pass
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in candidates:
        r = c.expanduser().resolve()
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def _download_from_github(target: Path) -> tuple[Path | None, str]:
    ensure_dir(target.parent)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "repo.zip"
            urllib.request.urlretrieve(TEXT2IMAGE_GITHUB_ZIP_URL, archive)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp)
            source = Path(tmp) / "kocotree-skills-master" / TEXT2IMAGE_GITHUB_SKILL_PATH
            if not _is_valid_skill(source):
                return None, f"GitHub 下载包中未找到有效 text2image skill：{source}"
            shutil.copytree(source, target)
    except Exception as exc:
        return None, f"从 GitHub 安装 text2image 失败：{exc}"
    if not _is_valid_skill(target):
        return None, f"text2image 安装后校验失败：{target}"
    return target, f"已从 GitHub 安装 text2image：{target}"


_resolve_lock = threading.Lock()
_resolve_cache: tuple[Path | None, str] | None = None


def _resolve_skill_dir() -> tuple[Path | None, str]:
    global _resolve_cache
    if _resolve_cache is not None:
        return _resolve_cache

    with _resolve_lock:
        if _resolve_cache is not None:
            return _resolve_cache

        for candidate in _find_local_candidates():
            if _is_valid_skill(candidate):
                _ensure_venv(candidate / "scripts")
                _resolve_cache = (candidate, f"已在本地找到 text2image：{candidate}")
                return _resolve_cache

        sibling = _current_skill_root().parent / "text2image"
        if sibling.exists():
            if _is_valid_skill(sibling):
                _ensure_venv(sibling / "scripts")
                _resolve_cache = (sibling, f"text2image 已安装：{sibling}")
                return _resolve_cache
            _resolve_cache = (None, f"text2image 目录已存在但结构不完整：{sibling}")
            return _resolve_cache

        installed, msg = _download_from_github(sibling)
        if installed:
            _ensure_venv(installed / "scripts")
        _resolve_cache = (installed, msg)
        return _resolve_cache


# ── Text removal execution ───────────────────────────────────

def _build_command(script_dir: Path, main_script: Path) -> list[str]:
    venv_py = _venv_python(script_dir)
    if not venv_py.exists():
        raise FileNotFoundError(
            f"text2image 虚拟环境 Python 不存在，请先在 {script_dir} 执行 uv sync：{venv_py}"
        )
    return [str(venv_py), str(main_script)]


def _parse_output(stdout: str) -> Path | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("success") is True and data.get("file"):
            return Path(data["file"]).expanduser().resolve()
    return None


def _get_timeout() -> int:
    try:
        return max(1, int(os.environ.get("TEXT2IMAGE_TIMEOUT", "")))
    except ValueError:
        return DEFAULT_TEXT2IMAGE_TIMEOUT


def _run_text_removal(source: Path, temp_dir: Path) -> tuple[Path | None, str]:
    skill_dir, msg = _resolve_skill_dir()
    if skill_dir is None:
        return None, msg
    script_dir = skill_dir / "scripts"
    main_script = script_dir / "main.py"
    if not main_script.exists():
        return None, f"text2image 脚本不存在：{main_script}"

    try:
        base_cmd = _build_command(script_dir, main_script)
    except Exception as exc:
        return None, f"text2image 调用环境不满足：{exc}"

    model = os.environ.get("TEXT2IMAGE_MODEL", DEFAULT_TEXT2IMAGE_MODEL)
    command = [
        *base_cmd,
        "--prompt", TEXT_REMOVAL_PROMPT,
        "--files", str(source),
        "--output-dir", str(temp_dir),
        "--model", model,
    ]
    try:
        result = subprocess.run(
            command, cwd=script_dir, check=False,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_get_timeout(),
        )
    except subprocess.TimeoutExpired:
        return None, f"text2image 模型去字超时，超过 {_get_timeout()} 秒"
    except Exception as exc:
        return None, f"text2image 模型去字调用失败：{exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return None, detail[:500] if detail else f"text2image 退出码 {result.returncode}"

    generated = _parse_output(result.stdout)
    if generated is None:
        return None, "text2image 未返回生成图片路径"
    if not generated.exists():
        return None, f"text2image 返回的生成图片不存在：{generated}"
    return generated, f"text2image 模型去字，模型 {model}，临时图 {generated}"


# ── Public API ───────────────────────────────────────────────

def ensure_text2image_ready() -> tuple[bool, str]:
    skill_dir, msg = _resolve_skill_dir()
    return skill_dir is not None, msg


def get_text_removal_temp_dir() -> Path:
    return ensure_dir(Path(__file__).resolve().parents[1] / "output" / "image-without-text-tmp")


def prune_temp_images(temp_dir: Path, keep: int = 100) -> None:
    images = sorted(
        [p for p in temp_dir.iterdir() if p.is_file() and p.suffix.lower() in TEMP_IMAGE_SUFFIXES],
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    for old in images[keep:]:
        old.unlink(missing_ok=True)


def process_offsite_sku_text_removal(
    source: Path,
    output: Path,
    max_bytes: int,
    report: dict,
    platform: str,
    cleanup_temp: bool = True,
) -> Path | None:
    """处理单张站外 SKU 标签去字并按原坐标安全回贴。

    功能说明：识别右侧商品卡片并向左增加安全余量，将右侧纵向裁片放入
    与原图同尺寸的模型输入画布；模型返回后校验宽高比和受保护区域，
    仅将彩色标签内部区域贴回原图。

    参数：
        source：原始 SKU 图片路径。
        output：最终 JPG 输出路径。
        max_bytes：最终文件大小上限。
        report：处理报告字典。
        platform：报告中的平台名称。
        cleanup_temp：是否清理超过保留数量的临时图片。
    返回值：
        成功时返回最终输出路径，失败时返回 None。
    """
    temp_dir = get_text_removal_temp_dir()
    try:
        ensure_dir(output.parent)
        source_image = open_image(source)
        logger.info("开始处理站外SKU去字：%s", source)
        try:
            plan = detect_right_card_plan(source_image)
        except CardCropError as exc:
            logger.warning("商品卡片识别失败，按原图输出：%s，原因：%s", source, exc)
            add_risk(report, "商品卡片或彩色标签识别失败，已按原图压缩输出",
                     源文件=str(source), 原因=str(exc))
            image = source_image
            actions = ["商品卡片或彩色标签识别失败，按原图压缩输出"]
        else:
            logger.info(
                "商品卡片识别完成：card_x=%d-%d，crop_x=%d-%d，标签数=%d",
                plan.card_left,
                plan.card_right - 1,
                plan.crop_left,
                source_image.width - 1,
                len(plan.label_boxes),
            )
            model_input = build_model_input(source_image, plan)
            model_input_path = temp_dir / f"{source.stem}-{uuid4().hex}-input.png"
            model_input.save(model_input_path, format="PNG")
            generated, message = _run_text_removal(model_input_path, temp_dir)
            actions = [
                f"识别右侧商品卡片，左侧安全余量{plan.card_left - plan.crop_left}px",
                f"模型输入尺寸{model_input.width}x{model_input.height}",
            ]
            if generated is None:
                logger.warning("模型去字失败，按原图输出：%s，原因：%s", source, message)
                image = source_image
                actions.append("text2image 模型去字失败，按原图压缩输出")
                add_risk(report, "模型去字失败，已按原图压缩输出",
                         源文件=str(source), 输出文件=str(output), 原因=message)
            else:
                try:
                    generated_image = open_image(generated)
                    normalized = normalize_model_output(generated_image, model_input.size)
                    audit = validate_protected_regions(source_image, normalized, plan)
                    if not audit["通过"]:
                        raise CardCropError(
                            "模型修改了标签文字区域以外的内容："
                            f"平均通道差异{audit['平均通道差异']}，"
                            f"明显变化比例{audit['明显变化比例']}"
                        )
                    image = composite_editable_regions(source_image, normalized, plan)
                    actions.extend([
                        message,
                        f"模型输出恢复到{model_input.width}x{model_input.height}",
                        "受保护区域差异验收通过",
                        "仅回贴彩色标签内部，标签边缘和其他区域保持原图",
                    ])
                    logger.info("站外SKU模型结果验收通过：%s", source)
                except Exception as exc:
                    logger.warning("模型结果验收失败，按原图输出：%s，原因：%s", source, exc)
                    image = source_image
                    actions.append("模型结果验收失败，按原图压缩输出")
                    add_risk(report, "模型结果验收失败，已按原图压缩输出",
                             源文件=str(source), 临时图=str(generated), 原因=str(exc))

        if image.size != source_image.size:
            raise CardCropError(f"最终拼接尺寸与原图不一致：{image.size} != {source_image.size}")
        actions.append(f"最终图保持原图尺寸{source_image.width}x{source_image.height}")
        image = fit_into_canvas(image, (800, 800))
        actions.append("适配到 800x800 画布")
        saved = save_jpg_under(
            image, output, max_bytes, report,
            source, platform, "800sku去除文字", actions,
        )
        logger.info("站外SKU去字处理结束：%s -> %s", source, saved or output)
        return saved
    except Exception as exc:
        add_failure(report, "站外SKU去字失败",
                    源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None
    finally:
        if cleanup_temp:
            prune_temp_images(temp_dir)
