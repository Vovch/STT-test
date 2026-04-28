from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Optional


def substitute_command_placeholders(part: str, *, transcript: str) -> str:
    tj = json.dumps(transcript, ensure_ascii=False)
    s = str(part).replace("{transcript_json}", tj)
    s = s.replace("{text_json}", tj)
    s = s.replace("{transcript}", transcript)
    s = s.replace("{text}", transcript)
    return s


def build_command_args(argv_line: str, *, transcript: str, use_shell: bool) -> tuple[list[str] | str, bool]:
    raw = (argv_line or "").strip()
    if use_shell:
        return substitute_command_placeholders(raw, transcript=transcript), True
    parts = shlex.split(raw, posix=os.name != "nt")
    return [substitute_command_placeholders(p, transcript=transcript) for p in parts], False


def run_transcript_command(
    argv_line: str,
    *,
    transcript: str,
    use_shell: bool,
    timeout_seconds: int,
    env: Optional[dict[str, str]] = None,
) -> str:
    line = (argv_line or "").strip()
    text = transcript.strip()
    if not line:
        raise RuntimeError("No command is configured for this tap count.")
    if not text:
        raise RuntimeError("No speech was recognized for command execution.")
    argv, shell = build_command_args(line, transcript=text, use_shell=use_shell)
    merged = {**(env or os.environ), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            shell=shell,
            env=merged,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Command timed out.") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {detail}")
    return (proc.stdout or "").strip()
