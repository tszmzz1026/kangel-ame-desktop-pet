"""发布前发现的故障回归。"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from pet import autostart, config
from pet.llm import LLMClient, parse_reply
from pet.memory import Memory
from pet.tts import TTSClient

APP = QCoreApplication.instance() or QCoreApplication([])


class ReleaseRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = copy.deepcopy(config.DEFAULT_CONFIG)

    def test_corrupt_config_is_preserved(self) -> None:
        path = Path(self.temp.name) / "config.json"
        path.write_text("{broken", encoding="utf-8")
        with patch.object(config, "CONFIG_PATH", str(path)):
            config.load_config()
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_invalid_section_uses_defaults(self) -> None:
        path = Path(self.temp.name) / "config.json"
        path.write_text(json.dumps({"tts": None, "pet": {"scale": 0}}))
        with patch.object(config, "CONFIG_PATH", str(path)):
            cfg = config.load_config()
        self.assertIsInstance(cfg["tts"], dict)
        self.assertGreater(cfg["pet"]["scale"], 0)

    def test_config_load_does_not_mutate_defaults(self) -> None:
        path = Path(self.temp.name) / "config.json"
        snapshot = copy.deepcopy(config.DEFAULT_CONFIG)
        with patch.object(config, "CONFIG_PATH", str(path)):
            cfg = config.load_config()
        cfg["tts"]["enabled"] = not cfg["tts"]["enabled"]
        self.assertEqual(config.DEFAULT_CONFIG, snapshot)

    def test_disabled_tts_does_not_preload(self) -> None:
        self.cfg["tts"]["enabled"] = False
        client = TTSClient(self.cfg)
        with patch("pet.tts.threading.Thread") as thread:
            client.preload_voice("ame")
        thread.assert_not_called()

    def test_failed_weights_are_not_marked_loaded(self) -> None:
        client = TTSClient(self.cfg)
        response = Mock(status_code=500, text="failed")
        with (
            patch("pet.tts.os.path.exists", return_value=True),
            patch("pet.tts.requests.get", return_value=response),
        ):
            voice = client._ensure_voice("cho")
        self.assertIsNone(voice)
        self.assertIsNone(client._loaded_voice)

    def test_stop_stops_sounddevice_playback(self) -> None:
        client = TTSClient(self.cfg)
        client._speaking = True
        client._stream = None
        with patch("pet.tts.sd.stop") as stop:
            client.stop()
        stop.assert_called_once()

    def test_timeout_change_rebuilds_client(self) -> None:
        path = Path(self.temp.name) / "memory.json"
        with patch.object(config, "MEMORY_PATH", str(path)):
            client = LLMClient(self.cfg)
        with patch.object(client, "_make_client", side_effect=lambda *args: Mock()):
            first = client._get_client()
            self.cfg["llm"]["timeout"] += 1
            second = client._get_client()
        self.assertIsNot(first, second)

    def test_model_options_must_be_a_list(self) -> None:
        reply = parse_reply('{"text":"やあ","options":"你好"}')
        self.assertEqual(reply["options"], [])

    def test_empty_memory_window_returns_no_messages(self) -> None:
        path = Path(self.temp.name) / "memory.json"
        with patch.object(config, "MEMORY_PATH", str(path)):
            memory = Memory()
            memory.add("user", "hello")
            self.assertEqual(memory.recent(0), [])

    def test_invalid_memory_messages_are_ignored(self) -> None:
        path = Path(self.temp.name) / "memory.json"
        path.write_text(json.dumps({"summary": None, "messages": [None, {}]}))
        with patch.object(config, "MEMORY_PATH", str(path)):
            memory = Memory()
        self.assertEqual(memory.messages, [])
        self.assertEqual(memory.summary, "")

    def test_frozen_autostart_uses_executable(self) -> None:
        with patch("sys.frozen", True, create=True), patch("sys.executable", r"C:\Pet Folder\Pet.exe"):
            command = autostart._build_command()
        self.assertEqual(command, '"C:\\Pet Folder\\Pet.exe"')

    def test_process_exit_preserves_status(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "from pet.process_exit import exit_process; exit_process(23)"],
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 23)


if __name__ == "__main__":
    unittest.main()
