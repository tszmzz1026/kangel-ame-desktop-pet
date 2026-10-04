"""解压正式附件，在中文路径运行 EXE 离线验收。"""

import json
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for label, variant in (("NoTTS", "no_tts"), ("TTS", "tts")):
        archive_path = ROOT / "release" / f"KangelAmePet-1.0.0-{label}-Windows-x64.zip"
        destination = ROOT / "build" / "正式发布中文路径验收" / variant
        with zipfile.ZipFile(archive_path) as archive:
            invalid = archive.testzip()
            if invalid:
                raise RuntimeError(f"压缩包校验失败: {invalid}")
            for name in archive.namelist():
                path = (destination / name).resolve()
                if not path.is_relative_to(destination.resolve()):
                    raise RuntimeError(f"不安全的压缩包路径: {name}")
                if any(
                    part in ("data", ".venv", ".buildenv", "screenshots", "train_raw")
                    for part in Path(name).parts
                ):
                    raise RuntimeError(f"发布包夹带本地数据: {name}")
            archive.extractall(destination)
        app_dir = destination / f"KangelAmePet-{label}"
        report_path = ROOT / "tools" / "out" / f"final_exe_{variant}" / "report.json"
        report_path.unlink(missing_ok=True)
        env = {**os.environ, "PET_DATA_DIR": str(report_path.parent), "QT_QPA_PLATFORM": "offscreen"}
        process = subprocess.run(
            [str(app_dir / f"KangelAmePet-{label}.exe"), "--self-test", str(report_path)],
            env=env,
            timeout=30,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if process.returncode != 0 or not report_path.is_file():
            raise RuntimeError(f"发布 EXE 验收失败: {variant}, 返回码 {process.returncode}")
        with report_path.open(encoding="utf-8") as stream:
            report = json.load(stream)
        if not report.get("ok"):
            raise RuntimeError(f"发布 EXE 检查失败: {variant}, {report['checks']}")
        if variant == "no_tts" and (app_dir / "tts_models").exists():
            raise RuntimeError("无 TTS 版夹带语音模型")
        if variant == "tts":
            models = list((app_dir / "tts_models").rglob("*"))
            if len([path for path in models if path.is_file()]) != 6:
                raise RuntimeError("有 TTS 版模型或参考音频不完整")
        print(f"{label}: 正式 ZIP、中文路径启动、{len(report['checks'])} 项 EXE 检查通过", flush=True)


if __name__ == "__main__":
    main()
