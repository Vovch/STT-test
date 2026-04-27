"""Run user-configured CLI for web search (default: OpenCode ``run`` with built-in prompt)."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
_STRIP_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def default_opencode_style_prompt(query: str) -> str:
    query = query.strip()
    if not query:
        return ""
    return (
        f"Search the web for this exact user query: {query}\n\n"
        f"User query: {query}\n\n"
        "Do not ask the user for another query. The query above is the complete query.\n"
        "Use OpenCode's websearch tool before answering.\n\n"
        "Return:\n"
        "- A concise answer in 4-8 bullets.\n"
        "- Practical takeaways first.\n"
        "- A final Sources section with clickable URLs.\n"
        "- A short uncertainty note if sources disagree or evidence is weak."
    )


def substitute_web_search_placeholders(part: str, *, query: str, prompt: str) -> str:
    """Replace ``{query_json}``, ``{prompt}``, ``{query}`` (longest keys first)."""
    qj = json.dumps(query, ensure_ascii=False)
    s = str(part).replace("{query_json}", qj)
    s = s.replace("{prompt}", prompt)
    s = s.replace("{query}", query)
    return s


def strip_ansi(text: str) -> str:
    if not text:
        return ""
    return _STRIP_ANSI.sub("", text)


def build_web_search_process_args(
    argv_line: str | None,
    *,
    query: str,
    use_shell: bool,
) -> tuple[list[str] | str, bool]:
    """Return ``(argv_or_string, shell)`` for ``subprocess.run``."""
    prompt = default_opencode_style_prompt(query)
    raw = (argv_line or "").strip()
    if not raw:
        exe = shutil.which("opencode") or "opencode"
        return [exe, "run", "--format", "default", prompt], False
    if use_shell:
        return substitute_web_search_placeholders(raw, query=query, prompt=prompt), True
    parts = shlex.split(raw, posix=os.name != "nt")
    return [substitute_web_search_placeholders(p, query=query, prompt=prompt) for p in parts], False


def run_web_search_cli(
    argv_line: str | None,
    *,
    query: str,
    use_shell: bool,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> str:
    """Run CLI and return stdout as Markdown/plain text (stderr merged into errors)."""
    query = query.strip()
    if not query:
        raise RuntimeError("No search query was recognized from the recording.")
    argv, shell = build_web_search_process_args(argv_line, query=query, use_shell=use_shell)
    merged: dict[str, str] = {**(env or os.environ), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=False,
            env=merged,
            timeout=max(1, int(timeout_seconds)),
            check=False,
            shell=shell,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            "Web search command timed out. Try a shorter query or increase "
            "`POTATO_STT_TIMEOUT_SECONDS` (web uses several times the STT timeout)."
        ) from e
    out_raw = proc.stdout if proc.stdout is not None else b""
    err_raw = proc.stderr if proc.stderr is not None else b""
    if proc.returncode != 0:
        detail = strip_ansi(
            (_decode_cli_bytes(err_raw) + _decode_cli_bytes(out_raw)).strip()
        )
        raise RuntimeError(f"Web search command failed (exit {proc.returncode}): {detail}")
    out = strip_ansi(_decode_cli_bytes(out_raw).strip())
    if not out:
        raise RuntimeError("Web search command returned an empty response.")
    return out


def _decode_cli_bytes(data: bytes | bytearray) -> str:
    if not data:
        return ""
    return bytes(data).decode("utf-8", errors="replace")
