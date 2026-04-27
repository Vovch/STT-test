"""Unit tests for web_search_runner (argv building + placeholders)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from potato_stt.web_search.runner import (
    build_web_search_process_args,
    default_opencode_style_prompt,
    run_web_search_cli,
    substitute_web_search_placeholders,
)


class WebSearchRunnerTests(unittest.TestCase):
    def test_default_prompt_contains_query(self) -> None:
        p = default_opencode_style_prompt("hello world")
        self.assertIn("hello world", p)
        self.assertIn("Sources", p)

    def test_substitute_order(self) -> None:
        s = substitute_web_search_placeholders("{query_json} {query}", query='a"b', prompt="p")
        self.assertIn('"a\\"b"', s)
        self.assertNotIn("{query}", s)

    def test_build_default_argv(self) -> None:
        with patch("potato_stt.web_search.runner.shutil.which", return_value="/bin/opencode"):
            argv, shell = build_web_search_process_args(None, query="q", use_shell=False)
        self.assertFalse(shell)
        self.assertEqual(argv[0], "/bin/opencode")
        self.assertEqual(argv[1], "run")
        self.assertIn("User query: q", argv[-1])

    def test_build_custom_argv_shlex(self) -> None:
        argv, shell = build_web_search_process_args(
            'echo hello {query}',
            query="x",
            use_shell=False,
        )
        self.assertFalse(shell)
        self.assertEqual(argv, ["echo", "hello", "x"])

    def test_run_cli_invokes_subprocess(self) -> None:
        import subprocess

        def _fake_run(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=b"ok out", stderr=b"")

        with patch("potato_stt.web_search.runner.shutil.which", return_value="oc"):
            with patch("potato_stt.web_search.runner.subprocess.run", _fake_run):
                out = run_web_search_cli(None, query="z", use_shell=False, timeout_seconds=30)
        self.assertEqual(out, "ok out")


if __name__ == "__main__":
    unittest.main()
