from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import venv
import zipfile
from pathlib import Path
from typing import Callable, Optional

import requests
import py7zr


def _patch_source_app(source_dir: Path) -> None:
    app_py = source_dir / "app.py"
    if not app_py.exists():
        return
    text = app_py.read_text(encoding="utf-8", errors="ignore")
    if "POTATO_STT_DISABLE_PARAKEET_WEBOPEN" in text or "PIPIT_DISABLE_PARAKEET_WEBOPEN" in text:
        patched = text
    else:
        patched = text.replace(
            "threading.Thread(target=openweb).start()",
            "if os.environ.get('POTATO_STT_DISABLE_PARAKEET_WEBOPEN', '1') != '1':\n"
            "        threading.Thread(target=openweb).start()",
        )

    # Patch for performance: avoid reloading ASR model on every request.
    if "MODEL_CACHE = {}" not in patched:
        anchor = "app.config['MAX_CONTENT_LENGTH'] = 20000 * 1024 * 1024  \n"
        insert = (
            "MODEL_CACHE = {}\n\n"
            "def get_or_load_model(language: str):\n"
            "    key = language\n"
            "    if key in MODEL_CACHE:\n"
            "        return MODEL_CACHE[key]\n"
            "    name_map = {\n"
            "        'default': 'parakeet-tdt-0.6b-v3',\n"
            "        'ja': 'parakeet-tdt_ctc-0.6b-ja',\n"
            "        'vi': 'parakeet-ctc-0.6b-Vietnamese',\n"
            "    }\n"
            "    if language == 'vi':\n"
            "        model = nemo_asr.models.ASRModel.restore_from(\n"
            "            restore_path=f'{MODEL_DIR}/models--nvidia--parakeet-ctc-0.6b-Vietnamese/"
            "snapshots/5be0ba9c9d4528b6c3a17c56b0b38c15fea9c3d6/parakeet-ctc-0.6b-vi.nemo'\n"
            "        )\n"
            "    else:\n"
            "        model = nemo_asr.models.ASRModel.from_pretrained(\n"
            "            model_name=f\"nvidia/{name_map.get(language, name_map['default'])}\"\n"
            "        )\n"
            "    MODEL_CACHE[key] = model\n"
            "    return model\n\n"
        )
        if anchor in patched:
            patched = patched.replace(anchor, anchor + insert)

    old_block = (
        "        if language=='vi':\n"
        "            asr_model = nemo_asr.models.ASRModel.restore_from(restore_path=f'{MODEL_DIR}/models--nvidia--parakeet-ctc-0.6b-Vietnamese/snapshots/5be0ba9c9d4528b6c3a17c56b0b38c15fea9c3d6/parakeet-ctc-0.6b-vi.nemo')\n"
        "        else:\n"
        "            asr_model = nemo_asr.models.ASRModel.from_pretrained(model_name=f'nvidia/{model_list[language]}')\n"
    )
    if old_block in patched:
        patched = patched.replace(old_block, "        asr_model = get_or_load_model(language)\n")

    if patched != text:
        app_py.write_text(patched, encoding="utf-8")


def _tail_text(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_chars), os.SEEK_SET)
        chunk = f.read().decode("utf-8", errors="ignore")
    return chunk


def _extract_model_download_percent(log_path: Optional[Path]) -> Optional[int]:
    if log_path is None or not log_path.exists():
        return None
    tail = _tail_text(log_path, max_chars=8000)
    # Example from HF snapshot_download progress:
    # "Fetching 4 files:  25%|██▌       | 1/4 [00:00<00:01,  2.31it/s]"
    matches = re.findall(r"Fetching\s+\d+\s+files:\s+(\d+)%", tail)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def _extract_error_hint(log_path: Optional[Path]) -> Optional[str]:
    if log_path is None or not log_path.exists():
        return None
    lines = _tail_text(log_path, max_chars=10000).splitlines()
    for line in reversed(lines):
        s = line.strip()
        if not s:
            continue
        if "Traceback" in s or "Error" in s or "ModuleNotFoundError" in s or "Exception" in s:
            return s
    return None


def _is_port_open(host: str, port: int, timeout_seconds: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _download_with_progress(
    url: str,
    dest_path: Path,
    *,
    on_progress: Optional[Callable[[float], None]] = None,
) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", "0") or "0")
        downloaded = 0

        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
        if tmp_path.exists():
            tmp_path.unlink()

        with tmp_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total and on_progress is not None:
                    on_progress(min(100.0, 100.0 * downloaded / total))

        tmp_path.replace(dest_path)
        if on_progress is not None:
            on_progress(100.0)


def _launch_bat(install_path: Path) -> None:
    log_path = install_path / "potato-stt-parakeet.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["POTATO_STT_DISABLE_PARAKEET_WEBOPEN"] = "1"
    # Legacy: older patched app.py checked PIPIT_DISABLE_PARAKEET_WEBOPEN.
    env["PIPIT_DISABLE_PARAKEET_WEBOPEN"] = "1"
    with log_path.open("a", encoding="utf-8") as logf:
        subprocess.Popen(
            ["cmd", "/c", "启动.bat"],
            cwd=str(install_path),
            stdout=logf,
            stderr=logf,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def _wait_until_port_open(
    *,
    host: str,
    port: int,
    timeout_seconds: int,
    on_status: Callable[[str], None],
    process: Optional[subprocess.Popen] = None,
    log_path: Optional[Path] = None,
) -> bool:
    deadline = time.time() + timeout_seconds
    last_pct: Optional[int] = None
    last_status = ""
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            hint = _extract_error_hint(log_path)
            if hint:
                on_status(f"Error: Parakeet exited (code {process.returncode}). {hint}")
            else:
                on_status(f"Error: Parakeet process exited early with code {process.returncode}.")
            return False
        if _is_port_open(host, port, timeout_seconds=1.0):
            return True
        pct = _extract_model_download_percent(log_path)
        if pct is not None:
            if pct != last_pct:
                msg = f"Model download {pct}%"
                on_status(msg)
                last_status = msg
                last_pct = pct
        else:
            msg = "Waiting for Parakeet service to finish model download..."
            if msg != last_status:
                on_status(msg)
                last_status = msg
        time.sleep(2.0)
    return False


def _fallback_run_source(
    *,
    install_path: Path,
    host: str,
    port: int,
    timeout_seconds: int,
    on_status: Callable[[str], None],
) -> bool:
    """
    Fallback if packaged archive URL is broken:
    - download parakeet-api source zip
    - install dependencies in current environment
    - run app.py
    """
    source_dir = install_path / "parakeet-api"
    app_py = source_dir / "app.py"
    if not app_py.exists():
        install_path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="potato-stt-parakeet-src-") as tmpdir:
            zip_path = Path(tmpdir) / "parakeet-api.zip"
            source_zip_url = "https://codeload.github.com/jianchang512/parakeet-api/zip/refs/heads/main"
            on_status("Package URL failed, downloading parakeet-api source fallback...")
            _download_with_progress(source_zip_url, zip_path)

            extract_root = Path(tmpdir) / "extracted"
            extract_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(str(extract_root))

            found = None
            for p in extract_root.rglob("app.py"):
                if p.parent.name.startswith("parakeet-api"):
                    found = p.parent
                    break
            if found is None:
                return False

            if source_dir.exists():
                shutil.rmtree(source_dir)
            shutil.copytree(found, source_dir)

    req = source_dir / "requirements.txt"
    if not req.exists():
        on_status("Fallback source mode missing requirements.txt.")
        return False

    _patch_source_app(source_dir)

    # IMPORTANT: use an isolated service venv to avoid mutating the app's own venv
    # (which can cause WinError 5 file-lock conflicts on numpy/torch).
    svc_venv_dir = source_dir / ".venv-service"
    if not svc_venv_dir.exists():
        on_status("Creating isolated Parakeet service venv...")
        venv.EnvBuilder(with_pip=True).create(str(svc_venv_dir))

    if os.name == "nt":
        svc_python = svc_venv_dir / "Scripts" / "python.exe"
    else:
        svc_python = svc_venv_dir / "bin" / "python"

    if not svc_python.exists():
        on_status("Service venv Python not found.")
        return False

    on_status("Installing fallback dependencies in isolated venv (first run may be long)...")
    install_proc = subprocess.run(
        [str(svc_python), "-m", "pip", "install", "-r", str(req)],
        cwd=str(source_dir),
        check=False,
    )
    if install_proc.returncode != 0:
        on_status(f"Fallback dependency install failed with exit code {install_proc.returncode}.")
        return False

    log_path = source_dir / "potato-stt-parakeet-fallback.log"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["POTATO_STT_DISABLE_PARAKEET_WEBOPEN"] = "1"
    env["PIPIT_DISABLE_PARAKEET_WEBOPEN"] = "1"
    with log_path.open("a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [str(svc_python), "app.py"],
            cwd=str(source_dir),
            stdout=logf,
            stderr=logf,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    return _wait_until_port_open(
        host=host,
        port=port,
        timeout_seconds=timeout_seconds,
        on_status=on_status,
        process=proc,
        log_path=log_path,
    )


def ensure_parakeet_service(
    *,
    api_host: str,
    api_port: int,
    api_base_url: str,
    parakeet_win_url: str,
    install_dir: str,
    auto_download: bool,
    source_fallback: bool,
    launch_timeout_seconds: int,
    on_status: Callable[[str], None],
) -> None:
    """
    Ensure the Parakeet TDT Windows all-in-one package is extracted and launched.

    The community-packaged "all-in-one" zip/7z includes a local server that exposes:
      - base: http://127.0.0.1:5092/v1
      - endpoint: /v1/audio/transcriptions
    """
    if _is_port_open(api_host, api_port, timeout_seconds=1.0):
        on_status("Parakeet STT is already running.")
        return

    install_path = Path(install_dir)
    bat_path = install_path / "启动.bat"

    if not bat_path.exists() and auto_download:
        try:
            on_status("Downloading Parakeet Windows package (first run may be large)...")
            install_path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="potato-stt-parakeet-") as tmpdir:
                archive_path = Path(tmpdir) / "parakeet-win.7z"

                def _progress(p: float) -> None:
                    on_status(f"Downloading... {p:0.0f}%")

                _download_with_progress(parakeet_win_url, archive_path, on_progress=_progress)
                on_status("Extracting package...")
                with py7zr.SevenZipFile(archive_path, mode="r") as z:
                    z.extractall(path=str(install_path))

            if not bat_path.exists():
                found = None
                for p in install_path.rglob("启动.bat"):
                    found = p
                    break
                if found is not None and found.parent != install_path:
                    subfolder = found.parent
                    for item in subfolder.iterdir():
                        target = install_path / item.name
                        if target.exists():
                            if target.is_dir():
                                shutil.rmtree(target)
                            else:
                                target.unlink()
                        shutil.move(str(item), str(target))
        except Exception as e:
            on_status(f"Archive download failed ({type(e).__name__}).")

    # Preferred: packaged launcher.
    if bat_path.exists():
        on_status(f"Starting Parakeet service on {api_host}:{api_port} ...")
        _launch_bat(install_path)
        if _wait_until_port_open(
            host=api_host,
            port=api_port,
            timeout_seconds=launch_timeout_seconds,
            on_status=on_status,
            log_path=install_path / "potato-stt-parakeet.log",
        ):
            on_status("Parakeet STT is ready.")
            return

    # Fallback: source-based service bootstrap.
    if source_fallback:
        on_status("Trying source fallback mode...")
        if _fallback_run_source(
            install_path=install_path,
            host=api_host,
            port=api_port,
            timeout_seconds=launch_timeout_seconds,
            on_status=on_status,
        ):
            on_status("Parakeet STT is ready (source fallback).")
            return

    raise TimeoutError(
        f"Failed to start Parakeet STT. Expected {api_base_url} on port {api_port}. "
        f"If the package URL changed, set POTATO_STT_PARAKEET_WIN_URL (or legacy PIPIT_PARKEET_WIN_URL) or set "
        f"POTATO_STT_PARAKEET_INSTALL_DIR to an already extracted folder containing 启动.bat."
    )

