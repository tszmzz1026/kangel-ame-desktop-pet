"""无 TTS 版的静音适配器。"""

from typing import Any

from PySide6.QtCore import QObject, Signal


class SilentTTSClient(QObject):
    started = Signal()
    finished = Signal(bool)
    voice_changed = Signal(str)

    def __init__(self, cfg: dict[str, Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._voice = cfg["behavior"].get("form", "cho")

    def voices(self) -> dict[str, dict[str, str]]:
        return {key: {"name": name} for key, name in self.voice_names().items()}

    def voice_names(self) -> dict[str, str]:
        return {"cho": "超天酱", "ame": "糖糖"}

    def current_voice(self) -> str:
        return self._voice

    def set_voice(self, key: str) -> bool:
        changed = key != self._voice
        self._voice = key
        return changed

    def demo_line(self, key: str | None = None) -> str:
        return ""

    def preload_voice(self, key: str) -> None:
        pass

    def warmup(self) -> None:
        pass

    def speak(self, text: str, voice: str | None = None) -> None:
        pass

    def is_speaking(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def refresh_config(self) -> None:
        pass
