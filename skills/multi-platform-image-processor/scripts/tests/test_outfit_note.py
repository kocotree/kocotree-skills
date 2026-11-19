from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from common.outfit_note import OutfitDetail, draw_outfit_note
from common.utils import new_report
from workflows.platform_processing import default_template_path, run_platform_processing


def test_outfit_note_reuses_only_safe_bottom_space(tmp_path: Path) -> None:
    """验证浅色留白复用、原画保护及有内容时扩展底部。"""
    image = Image.new("RGB", (790, 200), "#f0f0f0")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((12, 0, 780, 120), fill="#54342b")
    note = OutfitDetail(tmp_path / "搭配.png", None, "速干T", 125)
    rendered = draw_outfit_note(image, note, image.height)
    assert rendered.size == image.size
    assert ImageChops.difference(image, rendered).getbbox()[1] >= 145

    drawing.rectangle((8, 150, 260, 170), fill="red")
    rendered = draw_outfit_note(image, note, image.height)
    assert rendered.size == (790, 268)
    assert ImageChops.difference(image, rendered.crop((0, 0, 790, 200))).getbbox() is None
    assert rendered.getpixel((0, 250)) == (240, 240, 240)


def test_outfit_note_only_applies_to_jd_and_vip_and_stays_with_art(tmp_path: Path) -> None:
    """验证六平台分流、连图备注位置和超高切片。"""
    source = tmp_path / "输入"
    detail = source / "详情"
    detail.mkdir(parents=True)
    sku = source / "SKU" / "800"
    sku.mkdir(parents=True)
    Image.new("RGB", (800, 800), "blue").save(sku / "蓝色.jpg")
    for filename, height, color in (
        ("01.jpg", 130, "red"),
        ("02.jpg", 200, "orange"),
        ("03.jpg", 1780, "blue"),
        ("04.jpg", 140, "green"),
    ):
        Image.new("RGB", (790, height), color).save(detail / filename)
    plan = tmp_path / "计划.json"
    plan.write_text(json.dumps({"详情模块": [
        {"类型": "KV", "图片": "详情/01.jpg"},
        {"类型": "搭配", "图片": "详情/02.jpg", "连续组": "穿搭"},
        {"类型": "搭配", "图片": "详情/03.jpg", "连续组": "穿搭", "搭配备注": {"品类短名": "绒绒裤"}},
        {"类型": "模特", "图片": "详情/04.jpg"},
    ]}), encoding="utf-8")
    output_root = tmp_path / "输出"
    template = default_template_path()
    report = new_report(source, template, output_root)
    with patch("workflows.platform_processing.derive_offsite"):
        code, output = run_platform_processing(source, template, output_root, report, "TEST1", "测试商品", plan)
    assert code == 0, report["失败项"]
    expected_notes = [
        (output / "TEST1 测试商品-京东/详情页/790", 790),
        (output / "唯品会/750详情页", 750),
    ]
    for directory, width in expected_notes:
        assert sorted(path.name for path in directory.glob("*.jpg")) == [f"{n}.jpg" for n in range(601, 606)]
        with Image.open(directory / "604.jpg") as annotated:
            assert annotated.size == (width, 300)
            assert annotated.getpixel((0, 30))[2] > 200
            assert annotated.getpixel((0, 280)) == (255, 255, 255)
            gray_band = annotated.crop((0, 250, width, 283)).convert("L")
            assert gray_band.getextrema()[0] < 180
        with Image.open(directory / "602.jpg") as first:
            assert first.getpixel((0, first.height - 2))[0] > 200
        with Image.open(directory / "605.jpg") as following:
            assert following.getpixel((0, following.height - 2))[1] > 100
    with Image.open(output / "天猫通用版/790详情页/604.jpg") as tmall_tail:
        assert tmall_tail.height == 180
        assert tmall_tail.getpixel((0, 160))[2] > 200
    with Image.open(output / "CBME/750详情页/604.jpg") as cbme_tail:
        assert cbme_tail.height == 171
        assert cbme_tail.getpixel((0, 160))[2] > 200
    with Image.open(output / "蜂享家＋爱库存/790详情页/详情图-01.jpg") as fengxiang:
        assert fengxiang.height == 2250
