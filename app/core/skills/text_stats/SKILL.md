---
name: text_stats
description: Use when the user asks for exact word count, character count, sentence count, or estimated reading time for a piece of text. Don't count or estimate these yourself — run the script, LLMs are unreliable at exact counting.
---

# Text Stats

Computing exact counts by reading through text yourself is unreliable, especially for longer passages. This skill has a bundled script that computes them deterministically instead.

## Steps

1. Call `run_skill_script` with `skill_name="text_stats"`, `script_name="text_stats.py"`, and `script_args=["<the text to analyze>"]` (pass the full text as a single argument).
2. The script prints a JSON object with `word_count`, `char_count`, `char_count_no_spaces`, `sentence_count`, and `reading_time_minutes`.
3. Report the numbers directly from the script's output — don't recompute or adjust them.

## Available scripts

- `text_stats.py` — takes the text to analyze as its only argument, prints a JSON object of counts.
