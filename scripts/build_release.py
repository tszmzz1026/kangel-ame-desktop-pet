"""构建两种独立的 Windows 发布包。"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build"
RELEASE_DIR = ROOT / "release"
VERSION = "1.0.0"
MODEL_FILES = (
    "models/gptsovits/kangel/kangel_gpt_e22.ckpt",
    "models/gptsovits/kangel/kangel_sovits_e18.pth",
    "models/gptsovits/amechan/amechan_gpt_e24.ckpt",
    "models/gptsovits/amechan/amechan_sovits_e20.pth",
    "references/kangel/kangel_reference_010.wav",
    "references/amechan/amechan_reference_068.wav",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exclude_incompatible_icu(output: Path) -> None:
    library = output / "_internal" / "icuuc.dll"
    if not library.is_file():
        return
    with pefile.PE(str(library)) as image:
        symbols = {entry.name for entry in image.DIRECTORY_ENTRY_EXPORT.symbols}
    if b"ucnv_open" not in symbols:
        system_library = Path(os.getenv("SystemRoot", "C:/Windows")) / "System32" / "icuuc.dll"
        if not system_library.is_file():
            raise RuntimeError("Qt 需要 Windows 系统 ICU，请在受支持的 Windows 系统构建")
        library.unlink()
        print("已排除与 Qt 不兼容的第三方 ICU 库", flush=True)


def build_variant(variant: str, model_root: Path | None, repack_only: bool = False) -> Path:
    with_tts = variant == "tts"
    stage = BUILD_DIR / f"source_{variant}"
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "main.py", stage / "main.py")
    package = stage / "pet"
    package.mkdir(exist_ok=True)
    for source in (ROOT / "pet").glob("*.py"):
        if source.name == "tts.py" and not with_tts:
            continue
        shutil.copy2(source, package / source.name)
    (package / "build_info.py").write_text(
        f'APP_NAME = "超天酱/糖糖桌宠"\nVERSION = "{VERSION}"\nTTS_AVAILABLE = {with_tts}\n',
        encoding="utf-8",
    )
    name = f"KangelAmePet-{'TTS' if with_tts else 'NoTTS'}"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name",
        name,
        "--icon",
        str(ROOT / "assets" / "icon.ico"),
        "--distpath",
        str(ROOT / "dist" / variant),
        "--workpath",
        str(BUILD_DIR / f"pyinstaller_{variant}"),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(stage),
        "--add-data",
        f"{ROOT / 'assets'};assets",
        "--exclude-module",
        "PySide6.QtWebEngineCore",
        "--exclude-module",
        "PySide6.QtWebEngineWidgets",
        "--exclude-module",
        "PySide6.QtQml",
        "--exclude-module",
        "PySide6.QtQuick",
    ]
    if not with_tts:
        for module in (
            "pet.tts",
            "numpy",
            "sounddevice",
            "soundfile",
            "_sounddevice_data",
            "_soundfile_data",
        ):
            command.extend(["--exclude-module", module])
    command.append(str(stage / "main.py"))
    log_path = BUILD_DIR / f"build_{variant}.log"
    if not repack_only:
        with log_path.open("w", encoding="utf-8") as stream:
            subprocess.run(command, cwd=stage, stdout=stream, stderr=subprocess.STDOUT, check=True)
    output = ROOT / "dist" / variant / name
    exclude_incompatible_icu(output)
    shutil.copy2(ROOT / "README.md", output / "使用说明.md")
    shutil.copy2(ROOT / "docs" / "CHANGELOG.md", output / "修复说明.md")
    if with_tts and model_root is not None:
        for relative in MODEL_FILES:
            source = model_root / relative
            if not source.is_file():
                raise FileNotFoundError(f"缺少 TTS 模型或参考音频: {source}")
            target = output / "tts_models" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    RELEASE_DIR.mkdir(exist_ok=True)
    archive_path = RELEASE_DIR / f"KangelAmePet-{VERSION}-{'TTS' if with_tts else 'NoTTS'}-Windows-x64.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source in sorted(output.rglob("*")):
            if source.is_file():
                archive.write(source, source.relative_to(output.parent))
    print(f"{variant}: {archive_path.name} ({archive_path.stat().st_size / 1024**2:.1f} MiB)", flush=True)
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("tts", "no_tts", "all"), default="all")
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--repack-only", action="store_true", help="仅刷新附件与压缩包，应用代码需已编译")
    args = parser.parse_args()
    BUILD_DIR.mkdir(exist_ok=True)
    variants = ("no_tts", "tts") if args.variant == "all" else (args.variant,)
    for variant in variants:
        build_variant(variant, args.model_root, args.repack_only)
    hashes: list[str] = []
    for source in sorted(RELEASE_DIR.glob("*.zip")):
        digest = file_sha256(source)
        hashes.append(f"{digest}  {source.name}")
    (RELEASE_DIR / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
