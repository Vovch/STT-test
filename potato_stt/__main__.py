"""Entry point for `python -m potato_stt` and PyInstaller (console=False)."""

from __future__ import annotations

import sys


def _ensure_stdio_streams() -> None:
    """GUI apps on Windows may have sys.stdout/sys.stderr set to None (no console).

    Third-party code often assumes these streams exist and calls .write(); without this,
    model download / tqdm / logging can raise AttributeError during ONNX load.
    """

    if sys.stdout is not None and sys.stderr is not None:
        return

    class _NullTextIO:
        def write(self, data: object) -> int:
            if data is None:
                return 0
            try:
                return len(data)  # type: ignore[arg-type]
            except TypeError:
                return 0

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    _null = _NullTextIO()
    if sys.stdout is None:
        sys.stdout = _null  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _null  # type: ignore[assignment]


_ensure_stdio_streams()

from potato_stt.app import main  # noqa: E402


if __name__ == "__main__":
    main()
