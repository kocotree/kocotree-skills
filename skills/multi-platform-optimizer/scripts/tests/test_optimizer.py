from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import optimize_package  # noqa: E402


def make_image(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "PNG")


def test_full_package(tmp_path: Path) -> None:
    source = tmp_path / "测试商品"
    make_image(source / "主图" / "800" / "01.png", (800, 800), (240, 20, 20))
    make_image(source / "主图" / "750" / "02.png", (750, 1000), (20, 240, 20))
    make_image(source / "详情页" / "790" / "01.png", (790, 1800), (20, 20, 240))
    make_image(source / "详情页" / "790" / "02.png", (790, 1800), (40, 40, 200))
    make_image(source / "sku" / "800" / "红色.png", (800, 800), (200, 10, 10))

    output, summary = optimize_package(source)

    assert output == tmp_path / "测试商品-全平台"
    expected = {
        output / "主图" / "800" / "01.jpg": (800, 800),
        output / "主图" / "750" / "02.jpg": (750, 1000),
        output / "主图" / "1440" / "01.jpg": (1440, 1440),
        output / "主图" / "1080" / "02.jpg": (1080, 1440),
        output / "主图" / "750正" / "01.jpg": (750, 750),
        output / "主图" / "1920" / "02.jpg": (1440, 1920),
        output / "详情页" / "790" / "01.jpg": (790, 1800),
        output / "详情页" / "750" / "01.jpg": (750, 1709),
        output / "详情页" / "爱库存+蜂享家" / "详情图-01.jpg": (790, 3600),
        output / "SKU" / "通用sku.jpg": (800, 800),
        output / "SKU" / "京东.jpg": (800, 800),
        output / "SKU" / "唯品会.jpg": (800, 800),
    }
    for path, size in expected.items():
        assert path.is_file()
        assert path.stat().st_size <= 500 * 1024
        with Image.open(path) as image:
            assert image.format == "JPEG"
            assert image.size == size
    assert not (output / "SKU" / "通用sku").exists()
    assert not (output / "SKU" / "京东").exists()
    assert not (output / "SKU" / "唯品会").exists()
    assert summary["failures"] == []


def test_categories_are_independent(tmp_path: Path) -> None:
    source = tmp_path / "只有详情"
    make_image(source / "详情页" / "790" / "01.png", (790, 1000), (100, 100, 100))
    output, _ = optimize_package(source)
    assert (output / "详情页").is_dir()
    assert (output / "详情页" / "790.jpg").is_file()
    assert (output / "详情页" / "750.jpg").is_file()
    assert (output / "详情页" / "爱库存+蜂享家.jpg").is_file()
    assert not (output / "详情页" / "750").exists()
    assert not (output / "详情页" / "爱库存+蜂享家").exists()
    assert not (output / "主图").exists()
    assert not (output / "SKU").exists()


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "商品"
    (source / "主图").mkdir(parents=True)
    (tmp_path / "商品-全平台").mkdir()
    with pytest.raises(FileExistsError):
        optimize_package(source)


def test_already_named_source_is_not_modified(tmp_path: Path) -> None:
    source = tmp_path / "示例商品-全平台-改面料"
    original = source / "主图" / "800" / "01.png"
    make_image(original, (80, 80), (10, 20, 30))
    before = original.read_bytes()

    with pytest.raises(FileExistsError):
        optimize_package(source)

    assert original.read_bytes() == before
    assert list(source.iterdir()) == [source / "主图"]


@pytest.mark.parametrize(
    ("source_name", "expected_name"),
    [
        ("KQ12345 示例外套-改填充物", "KQ12345 示例外套-全平台-改填充物"),
        ("KQ12345 示例外套-尺码表去除100-120", "KQ12345 示例外套-全平台-尺码表去除100-120"),
        ("KQ-12345 示例外套－改面料", "KQ-12345 示例外套-全平台-改面料"),
        ("KQ12345 示例外套-全平台-改面料-优化", "KQ12345 示例外套-全平台-改面料"),
        ("KQ12345 示例外套-改面料-全平台-全平台-优化", "KQ12345 示例外套-全平台-改面料"),
    ],
)
def test_package_naming_preserves_change_notes(tmp_path: Path, source_name: str, expected_name: str) -> None:
    source = tmp_path / source_name
    make_image(source / "主图" / "800" / "01.png", (80, 80), (10, 20, 30))

    output, summary = optimize_package(source)

    assert output == tmp_path / expected_name
    assert (output / "主图" / "800.jpg").is_file()
    assert (source / "主图" / "800" / "01.png").is_file()
    assert summary["failures"] == []
    with pytest.raises(FileExistsError):
        optimize_package(source)


def test_bad_image_does_not_block_good_images(tmp_path: Path) -> None:
    source = tmp_path / "部分损坏"
    make_image(source / "主图" / "800" / "正常.png", (800, 800), (10, 20, 30))
    bad = source / "主图" / "800" / "损坏.jpg"
    bad.write_text("not an image", encoding="utf-8")
    output, summary = optimize_package(source)
    assert (output / "主图" / "1440" / "正常.jpg").is_file()
    assert summary["status"] == "部分完成"
    assert summary["failures"]


def test_single_main_image_uses_file_names_instead_of_subfolders(tmp_path: Path) -> None:
    source = tmp_path / "单张主图"
    make_image(source / "主图" / "800" / "唯一.png", (800, 800), (30, 60, 90))
    output, _ = optimize_package(source)
    expected = {
        "800.jpg": (800, 800),
        "1440.jpg": (1440, 1440),
        "1080.jpg": (1080, 1440),
        "750正.jpg": (750, 750),
        "1920.jpg": (1440, 1920),
    }
    for name, size in expected.items():
        path = output / "主图" / name
        assert path.is_file()
        with Image.open(path) as image:
            assert image.size == size
    assert not (output / "主图" / "1440").exists()
    assert not (output / "主图" / "800").exists()


def test_partial_detail_finds_original_and_replaces_region(tmp_path: Path) -> None:
    source = tmp_path / "改款商品-调整"
    changed = source / "详情页" / "790" / "修改图.png"
    make_image(changed, (790, 200), (240, 20, 20))
    original_package = tmp_path / "改款商品-全平台"
    original = original_package / "蜂享家＋爱库存" / "790详情页" / "详情图-01.jpg"
    make_image(original, (790, 1000), (80, 80, 80))
    untouched = original_package / "蜂享家＋爱库存" / "790详情页" / "详情图-02.jpg"
    make_image(untouched, (790, 1000), (20, 80, 120))
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "受影响原图": ["详情图-01.jpg"],
                "替换": [
                    {
                        "新图": "详情页/790/修改图.png",
                        "原图": "详情图-01.jpg",
                        "区域": [0, 400, 790, 600],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output, summary = optimize_package(source, partial_detail=True, replacement_map=mapping)

    result = output / "详情页" / "爱库存+蜂享家.jpg"
    assert result.is_file()
    assert (output / "详情页" / "790.jpg").is_file()
    assert not (output / "详情页" / "爱库存+蜂享家").exists()
    with Image.open(result) as image:
        center = image.convert("RGB").getpixel((395, 500))
        outside = image.convert("RGB").getpixel((395, 100))
    assert center[0] > 180 and center[1] < 80
    assert all(50 < value < 110 for value in outside)
    assert summary["partial_detail"]["replacement_count"] == 1


def test_partial_detail_reports_missing_original_package(tmp_path: Path) -> None:
    source = tmp_path / "找不到原款"
    make_image(source / "详情页" / "790" / "修改图.png", (790, 200), (240, 20, 20))
    with pytest.raises(FileNotFoundError, match="未找到原款全平台文件夹"):
        optimize_package(source, partial_detail=True, replacement_map=tmp_path / "mapping.json")


def test_multiple_partial_detail_images_keep_original_long_image_names(tmp_path: Path) -> None:
    source = tmp_path / "双图改款-调整"
    first = source / "详情页" / "790" / "修改1.png"
    second = source / "详情页" / "790" / "修改2.png"
    third = source / "详情页" / "790" / "修改3.png"
    make_image(first, (790, 200), (240, 20, 20))
    make_image(second, (790, 200), (20, 240, 20))
    make_image(third, (790, 200), (20, 20, 240))
    original_dir = tmp_path / "双图改款-全平台" / "爱库存+蜂享家" / "790详情页"
    make_image(original_dir / "详情图-01.jpg", (790, 1000), (80, 80, 80))
    make_image(original_dir / "详情图-02.jpg", (790, 1000), (90, 90, 90))
    mapping = tmp_path / "mapping-two.json"
    mapping.write_text(
        json.dumps(
            {
                "受影响原图": ["详情图-01.jpg", "详情图-02.jpg"],
                "替换": [
                    {"新图": "详情页/790/修改1.png", "原图": "详情图-01.jpg", "区域": [0, 400, 790, 600]},
                    {"新图": "详情页/790/修改2.png", "原图": "详情图-02.jpg", "区域": [0, 400, 790, 600]},
                    {"新图": "详情页/790/修改3.png", "原图": "详情图-01.jpg", "区域": [0, 0, 790, 200]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output, _ = optimize_package(source, partial_detail=True, replacement_map=mapping, original_package=original_dir.parents[1])

    result_dir = output / "详情页" / "爱库存+蜂享家"
    assert (output / "详情页" / "790" / "修改1.jpg").is_file()
    assert (output / "详情页" / "790" / "修改2.jpg").is_file()
    assert (output / "详情页" / "790" / "修改3.jpg").is_file()
    assert (result_dir / "详情图-01.jpg").is_file()
    assert (result_dir / "详情图-02.jpg").is_file()
    assert not (result_dir / "修改1.jpg").exists()
    assert len(list(result_dir.glob("*.jpg"))) == 2
    assert not (output / "详情页" / "爱库存+蜂享家.jpg").exists()


def test_detail_images_folder_is_used_when_790_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "images来源"
    make_image(source / "详情页" / "Images" / "01.png", (790, 1000), (40, 80, 120))
    output, summary = optimize_package(source)
    assert (source / "详情页" / "Images" / "01.png").is_file()
    assert not (source / "详情页" / "790").exists()
    assert (output / "详情页" / "790.jpg").is_file()
    assert (output / "详情页" / "750.jpg").is_file()
    assert (output / "详情页" / "爱库存+蜂享家.jpg").is_file()
    assert summary["status"] == "完成"


def test_images_directly_in_detail_root_create_required_outputs(tmp_path: Path) -> None:
    source = tmp_path / "详情根目录来源"
    make_image(source / "详情页" / "601.png", (790, 1000), (30, 60, 90))
    make_image(source / "详情页" / "602.png", (790, 1200), (60, 90, 120))

    output, summary = optimize_package(source)

    assert (source / "详情页" / "601.png").is_file()
    assert (output / "详情页" / "790" / "601.jpg").is_file()
    assert (output / "详情页" / "750" / "601.jpg").is_file()
    assert (output / "详情页" / "爱库存+蜂享家" / "详情图-01.jpg").is_file()
    assert summary["status"] == "完成"


def test_detail_reports_failure_without_790_or_images(tmp_path: Path) -> None:
    source = tmp_path / "缺少详情来源"
    (source / "详情页").mkdir(parents=True)
    output, summary = optimize_package(source)
    assert output.is_dir()
    assert summary["status"] == "部分完成"
    assert any("根目录都没有图片" in failure and "images" in failure for failure in summary["failures"])


def test_standalone_main_infers_identity_and_uses_flat_category_output(tmp_path: Path) -> None:
    (tmp_path / "KQ26168腰呼吸羽绒马甲-全平台检测报告未出").mkdir()
    source = tmp_path / "主图"
    make_image(source / "800" / "01.png", (800, 800), (20, 40, 60))
    make_image(source / "750" / "02.png", (750, 1000), (60, 80, 100))

    output, summary = optimize_package(source)

    assert output == tmp_path / "KQ26168 腰呼吸羽绒马甲-主图优化"
    assert (output / "800" / "01.jpg").is_file()
    assert (output / "750" / "02.jpg").is_file()
    assert (output / "1440" / "01.jpg").is_file()
    assert not (output / "主图").exists()
    assert summary["status"] == "完成"


def test_standalone_sku_uses_lowercase_sku_in_output_name(tmp_path: Path) -> None:
    (tmp_path / "KQ30001云朵外套-全平台").mkdir()
    source = tmp_path / "SKU"
    make_image(source / "唯一.png", (800, 800), (40, 60, 80))

    output, _ = optimize_package(source)

    assert output == tmp_path / "KQ30001 云朵外套-sku优化"
    assert (output / "通用sku.jpg").is_file()
    assert (output / "京东.jpg").is_file()
    assert (output / "唯品会.jpg").is_file()
    assert not (output / "SKU").exists()


def test_standalone_detail_can_infer_identity_from_parent(tmp_path: Path) -> None:
    product = tmp_path / "KQ40002 星星羽绒服"
    source = product / "详情页"
    make_image(source / "790" / "601.png", (790, 1000), (50, 70, 90))

    output, _ = optimize_package(source)

    assert output == product / "KQ40002 星星羽绒服-详情页优化"
    assert (output / "790.jpg").is_file()
    assert (output / "750.jpg").is_file()
    assert (output / "爱库存+蜂享家.jpg").is_file()
    assert not (output / "详情页").exists()


def test_standalone_category_rejects_multiple_product_codes(tmp_path: Path) -> None:
    (tmp_path / "KQ50001第一款-全平台").mkdir()
    (tmp_path / "KQ50002第二款-全平台").mkdir()
    source = tmp_path / "主图"
    make_image(source / "800" / "01.png", (800, 800), (20, 40, 60))

    with pytest.raises(RuntimeError, match="多个不同款号"):
        optimize_package(source)


def test_detail_near_full_platform_requires_explicit_classification(tmp_path: Path) -> None:
    source = tmp_path / "KQ60001改款外套-调整"
    make_image(source / "详情页" / "790" / "603.png", (790, 900), (30, 60, 90))
    (tmp_path / "KQ60001改款外套-全平台").mkdir()

    with pytest.raises(RuntimeError, match="禁止直接重拼"):
        optimize_package(source)

    output, summary = optimize_package(source, complete_detail=True)
    assert (output / "详情页" / "爱库存+蜂享家.jpg").is_file()
    assert summary["status"] == "完成"


def test_partial_detail_rejects_unmodified_original_in_affected_list(tmp_path: Path) -> None:
    source = tmp_path / "受影响集合校验-调整"
    make_image(source / "详情页" / "790" / "修改图.png", (790, 200), (240, 20, 20))
    original_dir = tmp_path / "受影响集合校验-全平台" / "爱库存+蜂享家" / "790详情页"
    make_image(original_dir / "详情图-01.jpg", (790, 1000), (80, 80, 80))
    make_image(original_dir / "详情图-02.jpg", (790, 1000), (90, 90, 90))
    mapping = tmp_path / "mapping-extra.json"
    mapping.write_text(
        json.dumps(
            {
                "受影响原图": ["详情图-01.jpg", "详情图-02.jpg"],
                "替换": [
                    {"新图": "详情页/790/修改图.png", "原图": "详情图-01.jpg", "区域": [0, 400, 790, 600]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output, summary = optimize_package(source, partial_detail=True, replacement_map=mapping)

    assert output.is_dir()
    assert summary["status"] == "部分完成"
    assert any("未发生替换却被列入" in failure for failure in summary["failures"])
    assert not (output / "详情页" / "爱库存+蜂享家").exists()


def test_detail_alias_and_full_width_replacement_can_change_height(tmp_path: Path) -> None:
    source = tmp_path / "高度变化改款-调整"
    changed = source / "详情" / "790" / "613.jpg"
    make_image(changed, (790, 300), (240, 120, 20))
    original_dir = tmp_path / "高度变化改款-全平台" / "爱库存+蜂享家" / "790详情页"
    original = original_dir / "详情图-05.jpg"
    make_image(original, (790, 1000), (80, 80, 80))
    mapping = tmp_path / "mapping-height.json"
    mapping.write_text(
        json.dumps(
            {
                "受影响原图": ["详情图-05.jpg"],
                "替换": [
                    {"新图": "详情/790/613.jpg", "原图": "详情图-05.jpg", "区域": [0, 100, 790, 500]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output, summary = optimize_package(source, partial_detail=True, replacement_map=mapping, original_package=original_dir.parents[1])

    result = output / "详情页" / "爱库存+蜂享家.jpg"
    assert result.is_file()
    with Image.open(result) as image:
        assert image.size == (790, 900)
    assert summary["status"] == "完成"


def test_partial_detail_insert_preserves_existing_long_image_content(tmp_path: Path) -> None:
    source = tmp_path / "新增详情模块-调整"
    changed = source / "详情页" / "790" / "613.jpg"
    make_image(changed, (790, 200), (240, 120, 20))
    original_dir = tmp_path / "新增详情模块-全平台" / "爱库存+蜂享家" / "790详情页"
    original = original_dir / "详情图-05.jpg"
    make_image(original, (790, 1000), (40, 80, 120))
    mapping = tmp_path / "mapping-insert.json"
    mapping.write_text(
        json.dumps(
            {
                "受影响原图": ["详情图-05.jpg"],
                "替换": [
                    {
                        "新图": "详情页/790/613.jpg",
                        "原图": "详情图-05.jpg",
                        "区域": [0, 0, 790, 0],
                        "操作": "插入",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output, summary = optimize_package(source, partial_detail=True, replacement_map=mapping)

    result = output / "详情页" / "爱库存+蜂享家.jpg"
    with Image.open(result) as image:
        assert image.size == (790, 1200)
        rgb = image.convert("RGB")
        assert rgb.getpixel((395, 100))[0] > 180
        assert rgb.getpixel((395, 700))[2] > rgb.getpixel((395, 700))[0]
    assert summary["status"] == "完成"
