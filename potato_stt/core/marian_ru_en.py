"""Local Russian→English translation using Helsinki-NLP OPUS-MT (Marian) on PyTorch CPU."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable, Optional

# Default: Helsinki OPUS-MT ru→en (Marian). Override with POTATO_STT_MARIAN_RU_EN_MODEL if needed.
_DEFAULT_MODEL = "Helsinki-NLP/opus-mt-ru-en"

_model = None
_tokenizer = None
_lock = threading.Lock()


def is_marian_weights_resident() -> bool:
    """True if tokenizer and weights are already loaded in this process."""
    with _lock:
        return _tokenizer is not None and _model is not None


def marian_model_id() -> str:
    raw = os.environ.get("POTATO_STT_MARIAN_RU_EN_MODEL", "").strip()
    return raw or _DEFAULT_MODEL


def is_translation_runtime_ready() -> bool:
    """True if PyTorch and transformers can import (translation can run after model download)."""
    try:
        import torch  # noqa: F401
        from transformers import MarianMTModel, MarianTokenizer  # noqa: F401

        return True
    except ImportError:
        return False


def _drop_torch_and_transformers_modules() -> None:
    keys = [
        k
        for k in list(sys.modules)
        if k == "torch"
        or k.startswith("torch.")
        or k == "transformers"
        or k.startswith("transformers.")
    ]
    for k in keys:
        sys.modules.pop(k, None)


def install_translation_runtime_packages(*, timeout_seconds: int = 900) -> tuple[int, str]:
    """Install CPU PyTorch + transformers stack via pip into the current interpreter.

    Returns (exit_code, combined_stdout_stderr). exit_code -1 means timeout or launch error.
    """
    args = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "torch",
        "transformers>=4.36.0,<5",
        "sentencepiece",
        "sacremoses",
        "--extra-index-url",
        "https://download.pytorch.org/whl/cpu",
    ]
    popen_kw: dict = {}
    if sys.platform == "win32":
        # Hide console window on Windows (pythonw / GUI apps).
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            **popen_kw,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + "\n" + (e.stderr or "")
        return -1, (out or "pip timed out").strip()
    except OSError as e:
        return -1, f"{type(e).__name__}: {e}"

    log_parts = []
    if completed.stdout:
        log_parts.append(completed.stdout.strip())
    if completed.stderr:
        log_parts.append(completed.stderr.strip())
    log = "\n\n".join(p for p in log_parts if p).strip()
    if not log:
        log = f"(pip finished with exit code {completed.returncode})"

    if completed.returncode == 0:
        _drop_torch_and_transformers_modules()

    return completed.returncode, log


def _load_marian_into_globals_locked(
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> None:
    """Load tokenizer + weights into module globals. Caller must hold ``_lock``."""
    # Avoid tokenizer fork/spawn warnings on Windows and free CPU for the UI thread during load.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    import torch
    from transformers import MarianMTModel, MarianTokenizer

    global _model, _tokenizer

    if _tokenizer is not None and _model is not None:
        return

    device = torch.device("cpu")
    mid = marian_model_id()
    if on_status is not None:
        on_status(
            "Downloading and loading Marian RU→EN model from Hugging Face "
            "(about 300 MB; internet required)…"
        )
    try:
        # Heavy download/load off the GUI thread; keep BLAS/OpenMP from saturating all cores.
        _cpus = os.cpu_count() or 1
        try:
            torch.set_num_threads(max(1, min(4, _cpus)))
            torch.set_num_interop_threads(1)
        except Exception:
            pass
        _tokenizer = MarianTokenizer.from_pretrained(mid)
        _model = MarianMTModel.from_pretrained(mid)
        _model.eval()
        _model.to(device)
    except Exception:
        _tokenizer = None
        _model = None
        raise


def preload_translation_model(
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> None:
    """Download and load Marian weights if missing (same cache as translate)."""
    if not is_translation_runtime_ready():
        raise RuntimeError(
            "PyTorch and transformers are not installed; cannot load the translation model."
        )
    with _lock:
        _load_marian_into_globals_locked(on_status=on_status)


def translate_ru_en(
    text: str,
    *,
    on_status: Optional[Callable[[str], None]] = None,
    model_fetch_allowed: bool = False,
) -> str:
    """Translate non-empty text; returns stripped English or original on empty input.

    ``model_fetch_allowed`` must be True (user enabled translation in **Options** and the fetch was approved)
    before weights are loaded from Hugging Face for the first time in this session (or from cache).
    """
    stripped = text.strip()
    if not stripped:
        return text

    try:
        import torch
        from transformers import MarianMTModel, MarianTokenizer  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "Local translation needs PyTorch (CPU) and transformers. From the repo venv, run:\n"
            "  pip install -r requirements-translate.txt\n"
            "  pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            f"Import error: {e}"
        ) from e

    global _model, _tokenizer

    device = torch.device("cpu")
    with _lock:
        resident = _tokenizer is not None and _model is not None
        if not resident and not model_fetch_allowed:
            raise RuntimeError(
                "The translation model is not loaded yet. Open **Options**, enable "
                "**Translate push-to-talk transcripts to English**, agree in the notice "
                "if asked, and wait for the Marian model (~300 MB) to finish downloading."
            )
        _load_marian_into_globals_locked(on_status=on_status)

        tokenizer = _tokenizer
        model = _model
        assert tokenizer is not None and model is not None

        batch = tokenizer(
            [stripped],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )
        batch = {k: v.to(device) for k, v in batch.items()}
        with torch.inference_mode():
            out_ids = model.generate(
                **batch,
                max_length=512,
                num_beams=4,
                early_stopping=True,
            )
        out = tokenizer.decode(out_ids[0], skip_special_tokens=True).strip()

    return out if out else text
