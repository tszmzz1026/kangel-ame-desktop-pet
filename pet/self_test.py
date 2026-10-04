"""源码及发布 EXE 共用的离线界面验收。"""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, QTimer

from . import config
from .build_info import TTS_AVAILABLE
from .settings_dialog import SettingsDialog

if TYPE_CHECKING:
    from .pet_window import PetWindow


def schedule_self_test(win: "PetWindow", report_path: Path, result: dict[str, bool]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    completed: list[int] = []
    checks: dict[str, bool] = {}

    def exercise() -> None:
        checks["animations_loaded"] = len(win.lib.manifest) >= 300
        checks["frames_exist"] = all(
            Path(config.resource(path)).is_file()
            for form in ("cho", "ame")
            for path in win.lib.frames(win.lib.pick_idle(form))
        )
        win.toggle_form()
        checks["switch_to_ame"] = win.engine.base_form() == "ame"
        win.grab().save(str(report_path.with_name("pet_ame.png")))
        win.toggle_form()
        checks["switch_to_cho"] = win.engine.base_form() == "cho"
        win.grab().save(str(report_path.with_name("pet_cho.png")))
        win.toggle_sleep()
        checks["sleep"] = win.engine.is_sleeping()
        win.toggle_sleep()
        checks["wake"] = not win.engine.is_sleeping()
        dialog = SettingsDialog(win.cfg, lambda cfg: None, parent=win)
        dialog.show()
        dialog.grab().save(str(report_path.with_name("settings.png")))
        checks["tts_controls"] = dialog.tts_enabled.isEnabled() == TTS_AVAILABLE
        dialog.close()
        for index in range(6):
            win.run_async(lambda index=index: index, completed.append)

    def finish() -> None:
        checks["async_results"] = sorted(completed) == list(range(6))
        checks["thread_cleanup"] = (
            not win._threads
            and not win._workers
            and not any(isinstance(child, QThread) for child in win.children())
        )
        checks["no_audio_imports"] = TTS_AVAILABLE or not any(
            name in sys.modules for name in ("pet.tts", "sounddevice", "soundfile", "numpy")
        )
        result["ok"] = bool(checks) and all(checks.values())
        with report_path.open("w", encoding="utf-8") as stream:
            json.dump(
                {"ok": result["ok"], "tts_available": TTS_AVAILABLE, "checks": checks}, stream, indent=4
            )
        win.quit()

    QTimer.singleShot(100, exercise)
    QTimer.singleShot(2500, finish)
