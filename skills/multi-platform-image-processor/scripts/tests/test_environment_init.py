from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import init as init_module
from auth import auth_client
from common import environment
from common import text_removal


class EnvironmentInitializationTests(unittest.TestCase):
    """验证初始化状态、工具检查和运行期环境边界。"""

    def tearDown(self) -> None:
        """清理模块级环境缓存。"""
        environment.load_environment_state.cache_clear()
        text_removal._resolve_skill_dir.cache_clear()

    def test_state_configures_runtime_paths(self) -> None:
        """验证初始化状态为运行进程提供固定工具路径。"""
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            state_path = temp_dir / "environment.json"
            pngquant = temp_dir / "pngquant"
            text2image = temp_dir / "text2image"
            with patch(
                "common.environment.environment_state_path",
                return_value=state_path,
            ), patch.dict(os.environ, {}, clear=False):
                environment.save_environment_state(pngquant, text2image)
                data = environment.configure_runtime_environment()

                self.assertEqual(data["pngquant"], str(pngquant.resolve()))
                self.assertEqual(os.environ["PNGQUANT_BIN"], str(pngquant.resolve()))
                self.assertEqual(
                    os.environ["TEXT2IMAGE_SKILL_DIR"],
                    str(text2image.resolve()),
                )

    def test_missing_state_stops_before_processing(self) -> None:
        """验证缺少初始化状态时给出统一初始化命令。"""
        with TemporaryDirectory() as temp_dir_value:
            missing = Path(temp_dir_value) / "missing.json"
            with patch(
                "common.environment.environment_state_path",
                return_value=missing,
            ):
                with self.assertRaisesRegex(RuntimeError, "uv run init.py"):
                    environment.load_environment_state()

    def test_pngquant_must_execute_successfully(self) -> None:
        """验证可执行文件异常退出时初始化失败。"""
        failed = subprocess.CompletedProcess(
            ["pngquant", "--version"],
            -6,
            stdout="",
            stderr="缺少动态库",
        )
        with patch("init.find_pngquant", return_value="/fake/pngquant"), patch(
            "init.subprocess.run",
            return_value=failed,
        ):
            with self.assertRaisesRegex(RuntimeError, "缺少动态库"):
                init_module.validate_pngquant()

    def test_state_is_written_after_all_initialization_steps(self) -> None:
        """验证工具和认证全部完成后写入初始化状态。"""
        with TemporaryDirectory() as temp_dir_value:
            temp_dir = Path(temp_dir_value)
            pngquant = temp_dir / "pngquant"
            text2image = temp_dir / "text2image"
            state_path = temp_dir / "environment.json"
            with patch("init.validate_current_venv"), patch(
                "init.validate_pngquant",
                return_value=pngquant,
            ), patch(
                "init.initialize_text2image",
                return_value=(text2image, "完成"),
            ), patch("init.initialize_token") as initialize_token, patch(
                "init.save_environment_state",
                return_value=state_path,
            ) as save_state:
                result = init_module.initialize_environment()

            self.assertEqual(result, state_path)
            initialize_token.assert_called_once_with()
            save_state.assert_called_once_with(pngquant, text2image)

    def test_runtime_text2image_does_not_install_dependencies(self) -> None:
        """验证运行期只接受初始化记录的 text2image 路径。"""
        with patch.dict(os.environ, {}, clear=True), patch(
            "common.text_removal._download_from_github",
        ) as download:
            ready, message = text_removal.ensure_text2image_ready()

        self.assertFalse(ready)
        self.assertIn("uv run init.py", message)
        download.assert_not_called()

    def test_runtime_auth_does_not_start_first_authorization(self) -> None:
        """验证运行期认证失效时不会发起首次授权。"""
        with patch.object(
            auth_client,
            "_is_access_token_expired",
            return_value=True,
        ), patch.object(
            auth_client,
            "_is_refresh_token_expired",
            return_value=True,
        ), patch.object(auth_client, "_get_auth_url") as get_auth_url:
            with self.assertRaisesRegex(RuntimeError, "uv run init.py"):
                auth_client.ensure_existing_token()

        get_auth_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
