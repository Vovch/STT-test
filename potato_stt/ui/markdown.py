"""Markdown helpers for the web-search result dialog."""

from __future__ import annotations


def markdown_fence(text: str) -> str:
    """Wrap text in a Markdown fenced code block, lengthening the fence if the text contains ```."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    fence = "```"
    while fence in t:
        fence += "`"
    return f"{fence}\n{t}\n{fence}"


def web_search_dialog_markdown(query: str, summary: str) -> str:
    """Build Markdown for the web-search result dialog (summary may contain Markdown from the model)."""
    q = query.strip()
    s = (summary or "").replace("\r\n", "\n").replace("\r", "\n")
    return "## Query\n\n" + markdown_fence(q) + "\n\n---\n\n## Summary\n\n" + s
