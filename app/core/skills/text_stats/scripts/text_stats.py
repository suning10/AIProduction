"""Compute exact text statistics. Bundled script for the text_stats skill.

Usage: python text_stats.py "<text to analyze>"
Prints a single JSON object to stdout.
"""

import json
import re
import sys

_WORDS_PER_MINUTE = 200


def compute_stats(text: str) -> dict:
    """Compute word/char/sentence counts and estimated reading time for text."""
    words = text.split()
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]

    return {
        "word_count": len(words),
        "char_count": len(text),
        "char_count_no_spaces": len(text.replace(" ", "").replace("\n", "").replace("\t", "")),
        "sentence_count": len(sentences),
        "reading_time_minutes": round(len(words) / _WORDS_PER_MINUTE, 2) if words else 0.0,
    }


def main() -> None:
    """Parse argv, print stats as JSON."""
    if len(sys.argv) != 2:
        print(json.dumps({"error": "expected exactly one argument: the text to analyze"}))
        sys.exit(1)

    print(json.dumps(compute_stats(sys.argv[1])))


if __name__ == "__main__":
    main()
