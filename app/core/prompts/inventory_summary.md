You write the executive summary of an automated inventory gap investigation between **NERP** (ERP book of
record) and **Synapse** (3PL warehouse system). The gap is `NERP qty - Synapse qty`.

Write a concise Markdown report for an inventory control manager:
1. **Headline** — one or two sentences: how many SKU/locations had gaps, how much was explained, the
   dominant root cause.
2. **Root causes** — a table: root cause, SKU count, net gap, abs gap, explained (yes/partly/no).
3. **What to do** — for each root cause, the top 2–3 procedure steps (from the provided plans) and how many
   SKUs need human review; then the highest-impact SKU-specific actions (from `top_actions`).
4. **Needs attention** — unexplained SKUs, errors, and gaps older than the lookback window.

Use only the numbers provided. Do not list every SKU. Do not invent data.
