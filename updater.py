"""GitHub version.json check and Windows onedir auto-update."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_RAW_GITHUB_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)$"
)


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    notes: str


def parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts or (0,))


def is_newer(remote_version: str, local_version: str) -> bool:
    return parse_version(remote_version) > parse_version(local_version)


def _github_api_url(raw_url: str) -> str | None:
    match = _RAW_GITHUB_RE.match(raw_url.strip())
    if match is None:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    branch = match.group("branch")
    path = match.group("path")
    return (
        f"https://api.github.com/repos/{owner}/{repo}/contents/"
        f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
    )


def _decode_json_bytes(raw: bytes) -> dict:
    text = raw.decode("utf-8-sig").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("version.json must be a JSON object")
    return payload


def _fetch_via_github_api(api_url: str, user_agent: str) -> dict | None:
    request = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        meta = json.loads(response.read().decode("utf-8-sig"))
    content = base64.b64decode(meta["content"]).decode("utf-8-sig")
    return _decode_json_bytes(content.encode("utf-8"))


def _fetch_via_raw_url(raw_url: str, user_agent: str) -> dict:
    parsed = urllib.parse.urlparse(raw_url.strip())
    query = urllib.parse.parse_qs(parsed.query)
    query["_"] = [str(int(time.time()))]
    busted_url = parsed._replace(query=urllib.parse.urlencode(query, doseq=True)).geturl()
    request = urllib.request.Request(
        busted_url,
        headers={"User-Agent": user_agent, "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return _decode_json_bytes(response.read())


def fetch_version_payload(version_url: str, user_agent: str) -> dict | None:
    url = version_url.strip()
    if not url:
        return None
    api_url = _github_api_url(url)
    if api_url:
        try:
            return _fetch_via_github_api(api_url, user_agent)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, KeyError):
            pass
    try:
        return _fetch_via_raw_url(url, user_agent)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def check_for_update(version_url: str, current_version: str, *, app_name: str = "App") -> UpdateInfo | None:
    user_agent = f"{app_name}/{current_version}"
    payload = fetch_version_payload(version_url, user_agent)
    if payload is None:
        return None
    remote_version = str(payload.get("version", "")).strip()
    if not remote_version or not is_newer(remote_version, current_version):
        return None
    return UpdateInfo(
        version=remote_version,
        url=str(payload.get("url", "")).strip(),
        notes=str(payload.get("notes", "")).strip(),
    )


def can_auto_update() -> bool:
    return getattr(sys, "frozen", False) and sys.platform == "win32"


def get_install_dir() -> Path:
    if can_auto_update():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_update_log_path() -> Path:
    return Path(tempfile.gettempdir()) / "NaverReport_update.log"


ProgressCallback = Callable[[int, int], None]


def validate_zip_file(zip_path: Path, min_bytes: int = 1024) -> None:
    if not zip_path.is_file():
        raise ValueError("다운로드 파일이 없습니다.")
    size = zip_path.stat().st_size
    if size < min_bytes:
        raise ValueError(f"다운로드 파일이 너무 작습니다 ({size} bytes).")
    with zip_path.open("rb") as handle:
        header = handle.read(4)
    if header[:2] != b"PK":
        raise ValueError("다운로드 파일이 zip 형식이 아닙니다 (GitHub 오류 페이지일 수 있습니다).")


def download_file(
    url: str,
    dest: Path,
    *,
    user_agent: str,
    on_progress: ProgressCallback | None = None,
    timeout: int = 600,
) -> None:
    request = urllib.request.Request(url.strip(), headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length", 0) or 0)
        downloaded = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)


def extract_zip_to_staging(zip_path: Path, staging_dir: Path) -> Path:
    """zip을 임시 폴더에 풀고 복사 원본 경로 반환."""
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(staging_dir)
    return staging_dir


def _write_update_batch(batch_path: Path) -> None:
  batch_path.write_text(
    r"""@echo off
setlocal EnableExtensions
set "STAGING=%~1"
set "INSTALL=%~2"
set "EXE=%~3"
set "INNER=%~4"
set "WAITEXE=%~5"
set "WAITPID=%~6"
set "LOG=%TEMP%\NaverReport_update.log"

>>"%LOG%" echo [%date% %time%] update start
>>"%LOG%" echo STAGING=%STAGING%
>>"%LOG%" echo INSTALL=%INSTALL%
>>"%LOG%" echo EXE=%EXE%

:wait_loop
timeout /t 1 /nobreak >nul
if not "%WAITPID%"=="" (
  tasklist /FI "PID eq %WAITPID%" 2>nul | find "%WAITPID%" >nul
  if not errorlevel 1 goto wait_loop
) else (
  tasklist /FI "IMAGENAME eq %WAITEXE%" 2>nul | find /I "%WAITEXE%" >nul
  if not errorlevel 1 goto wait_loop
)

>>"%LOG%" echo process ended, waiting file unlock
timeout /t 3 /nobreak >nul

if exist "%STAGING%\%INNER%\" (
  set "SRC=%STAGING%\%INNER%"
) else (
  set "SRC=%STAGING%"
)

>>"%LOG%" echo robocopy "%SRC%" "%INSTALL%"
robocopy "%SRC%" "%INSTALL%" /E /IS /IT /R:5 /W:2 /NFL /NDL /NJH /NJS
if errorlevel 8 (
  >>"%LOG%" echo robocopy failed code %errorlevel%
  goto fail
)

rd /s /q "%STAGING%" 2>nul
>>"%LOG%" echo starting %EXE%
start "" "%EXE%"
>>"%LOG%" echo update success
endlocal
del "%~f0"
exit /b 0

:fail
>>"%LOG%" echo update failed
msg * "업데이트 실패. 로그: %TEMP%\NaverReport_update.log"
endlocal
del "%~f0"
exit /b 1
""",
    encoding="utf-8",
  )


def schedule_apply_update(
    zip_path: Path,
    *,
    install_dir: Path | None = None,
    exe_name: str,
    zip_inner_folder: str | None = None,
    app_slug: str = "app",
) -> None:
    if not can_auto_update():
        raise RuntimeError("Auto-update works only in packaged exe builds.")

    validate_zip_file(zip_path)

    target_dir = install_dir or get_install_dir()
    inner = zip_inner_folder or target_dir.name
    exe_path = target_dir / exe_name
    staging_dir = Path(tempfile.gettempdir()) / f"NaverReport_staging_{os.getpid()}"

    try:
        extract_zip_to_staging(zip_path, staging_dir)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise RuntimeError(f"업데이트 zip 풀기 실패: {exc}") from exc

    batch_path = Path(tempfile.gettempdir()) / f"{app_slug}_update_{os.getpid()}.bat"
    _write_update_batch(batch_path)

    creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [
            "cmd.exe",
            "/c",
            str(batch_path),
            str(staging_dir),
            str(target_dir),
            str(exe_path),
            inner,
            exe_name,
            str(os.getpid()),
        ],
        creationflags=creationflags,
        close_fds=True,
    )

    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass
