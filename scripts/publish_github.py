"""使用已有 GitHub 登录发布源码与双版本附件，凭据只保留在内存。"""

import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, BinaryIO

import requests

ROOT = Path(__file__).resolve().parents[1]
REPO_NAME = "kangel-ame-desktop-pet"
EXPECTED_OWNER = "tszmzz1026"
TAG = "v1.0.0"


class UploadReader:
    mode = "rb"

    def __init__(self, stream: BinaryIO, name: str, total: int) -> None:
        self._stream = stream
        self._name = name
        self._total = total
        self._last_step = -1

    def fileno(self) -> int:
        return self._stream.fileno()

    def tell(self) -> int:
        return self._stream.tell()

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        step = self.tell() * 10 // max(1, self._total)
        if step > self._last_step:
            self._last_step = step
            print(f"{self._name}: {min(100, step * 10)}% 已发送", flush=True)
        return data


def get_token() -> str:
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        return token
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = fields.get("password", "")
    if not token:
        raise RuntimeError("GitHub 尚未登录，请先使用 Git Credential Manager 登录")
    return token


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api(session: requests.Session, method: str, path: str, **kwargs: Any) -> requests.Response:
    response = session.request(method, f"https://api.github.com{path}", timeout=60, **kwargs)
    if response.status_code >= 400 and response.status_code != 404:
        raise RuntimeError(f"GitHub {method} {path} 失败: HTTP {response.status_code}")
    return response


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def audit_source() -> None:
    names = git("ls-files").splitlines()
    prohibited = ("data/", ".venv/", ".buildenv/", "extracted/", "tts_models/", "tts_backend/")
    for name in names:
        if name.startswith(prohibited) or "__pycache__" in name:
            raise RuntimeError(f"禁止发布本地数据或环境: {name}")
        path = ROOT / name
        if path.suffix in (".py", ".md", ".txt", ".json", ".toml", ".bat", ".ps1"):
            content = path.read_text(encoding="utf-8-sig")
            if re.search(
                r"\bsk-[A-Za-z0-9_-]{20,}\b|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}", content
            ):
                raise RuntimeError(f"检测到疑似凭据，停止发布: {name}")
    print(f"源码检查通过: {len(names)} 个文件", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    with requests.Session() as session:
        session.headers.update(
            {"Authorization": f"Bearer {get_token()}", "Accept": "application/vnd.github+json"}
        )
        profile = api(session, "GET", "/user").json()
        owner = profile.get("login")
        if owner != EXPECTED_OWNER:
            raise RuntimeError(f"Git 登录账号 {owner} 与目标账号 {EXPECTED_OWNER} 不一致")
        repo_path = f"/repos/{owner}/{REPO_NAME}"
        existing = api(session, "GET", repo_path)
        print(f"GitHub 已登录: {owner}; 仓库存在: {existing.status_code == 200}", flush=True)
        if args.check_only:
            return
        audit_source()
        if existing.status_code == 404:
            repository = api(
                session,
                "POST",
                "/user/repos",
                json={
                    "name": REPO_NAME,
                    "description": "超天酱/糖糖桌宠 · Windows 双形象桌面宠物，有 TTS / 无 TTS 双版本",
                    "private": False,
                    "auto_init": False,
                },
            ).json()
        else:
            repository = existing.json()
            if repository.get("private"):
                raise RuntimeError("同名仓库是私有仓库，停止发布以保留原设置")
        remote_url = f"https://github.com/{owner}/{REPO_NAME}.git"
        remotes = git("remote").splitlines()
        if "origin" not in remotes:
            git("remote", "add", "origin", remote_url)
        elif git("remote", "get-url", "origin") != remote_url:
            raise RuntimeError("origin 与目标仓库不一致")
        git("push", "-u", "origin", "main")
        release_response = api(session, "GET", f"{repo_path}/releases/tags/{TAG}")
        if release_response.status_code == 404:
            release = api(
                session,
                "POST",
                f"{repo_path}/releases",
                json={
                    "tag_name": TAG,
                    "target_commitish": git("rev-parse", "HEAD"),
                    "name": "超天酱/糖糖桌宠 v1.0.0 · 有 TTS / 无 TTS",
                    "body": (ROOT / "docs" / "RELEASE_NOTES.md").read_text(encoding="utf-8"),
                    "draft": True,
                    "prerelease": False,
                },
            ).json()
        else:
            release = release_response.json()
        upload_url = release["upload_url"].split("{", 1)[0]
        existing_assets = {asset["name"]: asset for asset in release.get("assets", [])}
        for source in sorted((ROOT / "release").iterdir()):
            if source.suffix not in (".zip", ".txt"):
                continue
            if source.name in existing_assets:
                if existing_assets[source.name]["size"] != source.stat().st_size:
                    raise RuntimeError(f"已有同名附件大小不同: {source.name}")
                continue
            print(f"上传: {source.name} ({source.stat().st_size / 1024**2:.1f} MiB)", flush=True)
            with source.open("rb") as stream:
                response = session.post(
                    upload_url,
                    params={"name": source.name},
                    data=UploadReader(stream, source.name, source.stat().st_size),
                    headers={"Content-Type": "application/zip" if source.suffix == ".zip" else "text/plain"},
                    timeout=(30, 1800),
                )
            if response.status_code != 201:
                raise RuntimeError(f"上传附件失败: {source.name}, HTTP {response.status_code}")
        uploaded = api(session, "GET", f"{repo_path}/releases/{release['id']}").json()
        assets = {asset["name"]: asset for asset in uploaded["assets"]}
        for source in (ROOT / "release").iterdir():
            if source.suffix not in (".zip", ".txt"):
                continue
            asset = assets.get(source.name)
            if asset is None or asset["size"] != source.stat().st_size:
                raise RuntimeError(f"远端附件不完整: {source.name}")
            if asset.get("digest"):
                digest = f"sha256:{file_sha256(source)}"
                if asset["digest"] != digest:
                    raise RuntimeError(f"远端校验值不一致: {source.name}")
        api(session, "PATCH", f"{repo_path}/releases/{release['id']}", json={"draft": False})
        final = api(session, "GET", f"{repo_path}/releases/{release['id']}").json()
        print(f"发布完成: {final['html_url']}", flush=True)
        for asset in final["assets"]:
            print(f"{asset['name']}: {asset['browser_download_url']}", flush=True)


if __name__ == "__main__":
    main()
