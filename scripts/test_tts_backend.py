"""真实双音色合成验收，不调用聊天 API，不播放音频。"""

import argparse
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import soundfile as sf
from PySide6.QtCore import QCoreApplication

from pet import config
from pet.textclean import clean_for_tts
from pet.tts import TTSClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    app = QCoreApplication([])
    cfg = copy.deepcopy(config.DEFAULT_CONFIG)
    cfg["tts"]["sovits_dir"] = str(args.backend)
    cfg["tts"]["ka_tts_dir"] = str(args.models)
    cfg["tts"]["enabled"] = True
    tts = TTSClient(cfg)
    results: dict[str, float | bool] = {}
    audio: list[bytes] = []
    try:
        if not tts._ensure_api():
            raise RuntimeError("GPT-SoVITS 后端启动失败")
        for key in ("cho", "ame"):
            voice = tts._ensure_voice(key)
            if voice is None:
                raise RuntimeError(f"音色加载失败: {key}")
            wav = tts.synthesize(clean_for_tts(tts.demo_line(key)), voice)
            if not wav:
                raise RuntimeError(f"音色合成失败: {key}")
            with sf.SoundFile(io.BytesIO(wav)) as stream:
                duration = len(stream) / stream.samplerate
                if not 0.5 < duration < 30:
                    raise RuntimeError(f"音频时长异常: {key}, {duration}")
            results[key] = duration
            audio.append(wav)
            print(f"{key}: 合成通过 ({duration:.2f}s)", flush=True)
        results["different_audio"] = audio[0] != audio[1]
        results["ok"] = bool(results["different_audio"])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8") as stream:
            json.dump(results, stream, indent=4)
    finally:
        tts.close()
        app.processEvents()


if __name__ == "__main__":
    main()
