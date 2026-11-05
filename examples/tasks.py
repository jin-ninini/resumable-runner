"""Example tasks for `resumable run`. Each takes one item's payload (a dict) and returns JSON."""

from __future__ import annotations

import re
import urllib.request
from typing import Any


def word_stats(item: dict[str, Any]) -> dict[str, Any]:
    """Offline example: count letters and vowels in the `word` column."""
    word = str(item["word"])
    return {"word": word, "letters": len(word), "vowels": sum(c in "aeiou" for c in word.lower())}


def fetch_title(item: dict[str, Any]) -> str:
    """Network example: return the <title> of the page in the `url` column.

    Raises on HTTP errors or timeouts so the runner can retry, back off, and
    stop early with --max-consecutive-failures if the site starts blocking you.
    """
    with urllib.request.urlopen(item["url"], timeout=10) as resp:
        html = resp.read(200_000).decode("utf-8", errors="replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        raise ValueError("no <title> found")
    return match.group(1).strip()
