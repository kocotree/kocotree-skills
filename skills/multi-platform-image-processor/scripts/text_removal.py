from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path

from common import ensure_dir, add_failure, add_risk
from image_resize_compress import fit_into_canvas, open_image, save_jpg_under


DEFAULT_TEXT2IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_TEXT2IMAGE_TIMEOUT = 300
TEXT2IMAGE_GITHUB_ZIP_URL = "https://github.com/ranjingya/kocotree-skills/archive/refs/heads/master.zip"
TEXT2IMAGE_GITHUB_SKILL_PATH = Path("skills") / "text2image"
TEMP_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_REMOVAL_PROMPT = (
    "去除图片中的文字，其他全部保持不变"
)


def is_text2image_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").exists() and (path / "scripts" / "main.py").exists()


def read_skill_name(path: Path) -> str:
    try:
        for line in (path / "SKILL.md").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("name:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        return ""
    return ""


def codex_home() -> Path:
    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return Path.home() / ".codex"


def current_skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def local_agent_skills_root() -> Path:
    return codex_home() / "skills"


def iter_local_agent_text2image_candidates() -> list[Path]:
    skills_root = local_agent_skills_root()
    candidates = [skills_root / "text2image"]

    if skills_root.exists():
        try:
            candidates.extend(path for path in skills_root.rglob("text2image") if path.is_dir())
            candidates.extend(skill_md.parent for skill_md in skills_root.rglob("SKILL.md") if read_skill_name(skill_md.parent) == "text2image")
        except OSError:
            pass

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(resolved)
    return unique_candidates


def sibling_text2image_skill_dir() -> Path:
    return current_skill_root().parent / "text2image"


def install_text2image_skill() -> tuple[Path | None, str]:
    target = sibling_text2image_skill_dir()
    if target.exists():
        if is_text2image_skill_dir(target) and read_skill_name(target) == "text2image":
            return target, f"text2image已安装：{target}"
        return None, f"text2image安装目录已存在但结构不完整：{target}"

    ensure_dir(target.parent)
    try:
        with tempfile.TemporaryDirectory() as temp_root:
            temp_dir = Path(temp_root)
            archive = temp_dir / "kocotree-skills-master.zip"
            urllib.request.urlretrieve(TEXT2IMAGE_GITHUB_ZIP_URL, archive)
            with zipfile.ZipFile(archive) as zip_file:
                zip_file.extractall(temp_dir)

            source = temp_dir / "kocotree-skills-master" / TEXT2IMAGE_GITHUB_SKILL_PATH
            if not is_text2image_skill_dir(source) or read_skill_name(source) != "text2image":
                return None, f"GitHub下载包中未找到有效text2image skill：{source}"

            shutil.copytree(source, target)
    except Exception as exc:
        return None, f"从GitHub安装text2image失败：{exc}"

    if is_text2image_skill_dir(target) and read_skill_name(target) == "text2image":
        return target, f"已从GitHub安装text2image：{target}"
    return None, f"text2image安装后校验失败：{target}"


@lru_cache(maxsize=1)
def resolve_text2image_skill_dir() -> tuple[Path | None, str]:
    for candidate in iter_local_agent_text2image_candidates():
        if is_text2image_skill_dir(candidate) and read_skill_name(candidate) == "text2image":
            return candidate, f"已在本地Agent skills目录找到text2image：{candidate}"

    installed, install_message = install_text2image_skill()
    if installed is not None:
        return installed, install_message

    return None, install_message


def get_text2image_skill_dir() -> Path | None:
    skill_dir, _ = resolve_text2image_skill_dir()
    return skill_dir


def get_text_removal_temp_dir() -> Path:
    return ensure_dir(Path(__file__).resolve().parent / "output" / "image-without-text-tmp")


def get_text2image_timeout() -> int:
    value = os.environ.get("TEXT2IMAGE_TIMEOUT", "")
    try:
        timeout = int(value)
    except ValueError:
        return DEFAULT_TEXT2IMAGE_TIMEOUT
    return max(1, timeout)


def build_text2image_command(script_dir: Path, main_script: Path) -> list[str]:
    venv_python = script_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        raise FileNotFoundError(f"text2image虚拟环境Python不存在，请先在 {script_dir} 执行 uv sync：{venv_python}")

    return [str(venv_python), str(main_script)]


def prune_temp_images(temp_dir: Path, keep: int = 100) -> None:
    images = sorted(
        [path for path in temp_dir.iterdir() if path.is_file() and path.suffix.lower() in TEMP_IMAGE_SUFFIXES],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for old_image in images[keep:]:
        old_image.unlink(missing_ok=True)


def parse_text2image_output(stdout: str) -> Path | None:
    for line in reversed([item.strip() for item in stdout.splitlines() if item.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("success") is True and data.get("file"):
            return Path(data["file"]).expanduser().resolve()
    return None


def run_text2image_text_removal(source: Path, temp_dir: Path) -> tuple[Path | None, str]:
    skill_dir, resolve_message = resolve_text2image_skill_dir()
    if skill_dir is None:
        return None, resolve_message
    script_dir = skill_dir / "scripts"
    main_script = script_dir / "main.py"
    if not main_script.exists():
        return None, f"text2image脚本不存在：{main_script}"

    try:
        base_command = build_text2image_command(script_dir, main_script)
    except Exception as exc:
        return None, f"text2image调用环境不满足：{exc}"

    model = os.environ.get("TEXT2IMAGE_MODEL", DEFAULT_TEXT2IMAGE_MODEL)
    command = [
        *base_command,
        "--prompt",
        TEXT_REMOVAL_PROMPT,
        "--files",
        str(source),
        "--output-dir",
        str(temp_dir),
        "--model",
        model,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=script_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=get_text2image_timeout(),
        )
    except subprocess.TimeoutExpired:
        return None, f"text2image模型去字超时，超过{get_text2image_timeout()}秒"
    except Exception as exc:
        return None, f"text2image模型去字调用失败：{exc}"

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return None, detail[:500] if detail else f"text2image退出码{result.returncode}"

    generated = parse_text2image_output(result.stdout)
    if generated is None:
        return None, "text2image未返回生成图片路径"
    if not generated.exists():
        return None, f"text2image返回的生成图片不存在：{generated}"
    return generated, f"text2image模型去字，模型{model}，临时图{generated}"


def process_offsite_sku_text_removal(
    source: Path,
    output: Path,
    max_bytes: int,
    report: dict,
    platform: str,
    cleanup_temp: bool = True,
) -> Path | None:
    temp_dir = get_text_removal_temp_dir()
    try:
        ensure_dir(output.parent)
        generated, message = run_text2image_text_removal(source, temp_dir)
        image_source = generated if generated else source
        actions = [message] if generated else ["text2image模型去字失败，按原图压缩输出"]
        try:
            image = open_image(image_source)
        except Exception as exc:
            if generated:
                add_risk(report, "模型生成图无法读取，已按原图压缩输出", 源文件=str(source), 临时图=str(generated), 原因=str(exc))
                image = open_image(source)
                actions = ["text2image模型生成图无法读取，按原图压缩输出"]
            else:
                raise
        image = fit_into_canvas(image, (800, 800))
        actions.append("适配到800x800画布")
        saved = save_jpg_under(
            image,
            output,
            max_bytes,
            report,
            source,
            platform,
            "800sku去除文字",
            actions,
        )
        if generated is None:
            add_risk(report, "模型去字失败，已按原图压缩输出", 源文件=str(source), 输出文件=str(saved or output), 原因=message)
        return saved
    except Exception as exc:
        add_failure(report, "站外SKU去字失败", 源文件=str(source), 输出文件=str(output), 错误=str(exc))
        return None
    finally:
        if cleanup_temp:
            prune_temp_images(temp_dir)
