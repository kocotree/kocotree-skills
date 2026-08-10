from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont

from .settings import config_root, load_json_config, skill_root


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FontAsset:
    """保存字体角色、文件、字体族和字形集合。"""

    role: str
    path: Path
    family: str
    glyphs: frozenset[int]


def _font_families(font: TTFont) -> set[str]:
    families: set[str] = set()
    for record in font["name"].names:
        if record.nameID not in {1, 16}:
            continue
        try:
            value = record.toUnicode().strip()
        except UnicodeDecodeError:
            continue
        if value:
            families.add(value)
    return families


def load_font_assets(
    config_path: Path | None = None,
    assets_root: Path | None = None,
) -> dict[str, FontAsset]:
    """加载并核对全部业务字体。

    参数：
        config_path：可选的字体角色配置文件。
        assets_root：可选的字体资产目录。
    返回值：
        字体角色到已校验字体资产的映射。
    """
    config = load_json_config(config_path or config_root() / "font_roles.json")
    root = assets_root or skill_root() / "assets"
    loaded: dict[str, FontAsset] = {}
    for role, raw in config.items():
        if not isinstance(raw, dict):
            raise RuntimeError(f"字体角色配置无效：{role}")
        path = root / str(raw.get("文件", ""))
        expected_family = str(raw.get("字体族", "")).strip()
        if not path.is_file():
            raise RuntimeError(f"字体文件缺失：{path}")
        try:
            font = TTFont(path, lazy=False)
            families = _font_families(font)
            glyphs = frozenset((font.getBestCmap() or {}).keys())
            font.close()
        except Exception as exc:
            raise RuntimeError(f"字体无法加载：{path}，{exc}") from exc
        if expected_family not in families:
            raise RuntimeError(
                f"字体内部名称不匹配：{path}，期望 {expected_family}，实际 {sorted(families)}"
            )
        loaded[role] = FontAsset(role, path, expected_family, glyphs)
        logger.info("字体加载完成 role=%s family=%s path=%r", role, expected_family, str(path))
    return loaded


def require_glyphs(asset: FontAsset, text: str) -> None:
    """确认字体包含目标文本的全部字形。

    参数：
        asset：已加载的字体资产。
        text：准备渲染的文本。
    返回值：
        无返回值；缺字时抛出运行错误。
    """
    missing = sorted({character for character in text if ord(character) not in asset.glyphs})
    if missing:
        raise RuntimeError(f"字体 {asset.family} 缺少字形：{''.join(missing)}")
