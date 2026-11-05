# PDF Parser Comparison: How to Run

This compares two PDF parsers, **pypdf** (fast, plain text) and **docling** (layout-aware markdown), end to end:
parse → chunk → embed → retrieve → score. Both use the same chunking and embedding, so any difference in
results comes from the parser.

There are two ways to run it:

| Option | Needs | Script |
|---|---|---|
| **A. Fully local, no database** | Ollama | `scripts/local_parser_eval.py` |
| **B. Real pgvector path** | Ollama + Docker (Postgres only) | `scripts/local_pg_eval.sh` |

Both read PDFs from `/Users/mw/Documents/AI/PDFS`, including all its subfolders.

---

## 1. One-time setup

Run everything from the project root:

```bash
cd /Users/mw/PycharmProjects/AIProduction
```

### 1.1 Install Python dependencies

```bash
uv sync
```

This installs `pypdf`, `docling`, `langchain-ollama` and `rich`, among others.

### 1.2 Install and start Ollama

```bash
ollama serve                      # skip if Ollama is already running (e.g. the menu-bar app)
ollama pull nomic-embed-text      # embedding model, required
ollama pull qwen3.5:0.8b          # chat model, only needed for --answer in option A
```

Check it's up:

```bash
curl -s http://localhost:11434/api/tags
```

### 1.3 Docker (option B only)

Make sure Docker Desktop is running:

```bash
docker info > /dev/null && echo "docker ok"
```

---

## 2. Option A: Fully local (no database)

Parses the PDFs, embeds the chunks with Ollama, and searches them in memory.

### Step 1: Quick smoke test on 5 PDFs

```bash
uv run python scripts/local_parser_eval.py --limit 5
```

### Step 2: Full run on all PDFs

```bash
uv run python scripts/local_parser_eval.py
```

The first run is slow: docling parses on CPU at roughly 5–90 seconds per PDF. The results are cached, so
later runs take seconds.

### Step 3 (optional): Generate answers and inspect chunks

```bash
uv run python scripts/local_parser_eval.py --answer --show-chunks --report ~/local_eval.json
```

- `--answer`: `qwen3.5:0.8b` answers each query from the top-5 chunks retrieved for each parser, so you can
  compare the answers side by side.
- `--show-chunks`: prints the top-ranked chunk for each parser.
- `--report PATH`: writes the full results as JSON.

### Useful options

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | `/Users/mw/Documents/AI/PDFS` | PDF folder |
| `--parsers ...` | `pypdf docling` | Which parsers to compare |
| `--limit N` | all | Only use the first N PDFs |
| `--top-k N` | 5 | Chunks retrieved per query |
| `--chunk-size / --chunk-overlap` | 1000 / 150 | Same as the app's settings |
| `--embed-model` | `nomic-embed-text` | Ollama embedding model |
| `--llm-model` | `qwen3.5:0.8b` | Ollama chat model for `--answer` |
| `--ocr` | off | Docling OCR, for scanned PDFs (slow) |
| `--no-cache` | off | Re-parse and re-embed everything |
| `--no-trace` | off | Turn off Langfuse tracing even if it's configured |

The cache lives in `~/.cache/aiproduction/parser_eval/`. Parsed text is in `text/<parser>/…md`, which is
handy for diffing parser output by eye. Delete the folder to start fresh.

---

## 3. Option B: Real pgvector path (Docker Postgres + Ollama)

This goes through the app's actual `RAGService`: the Postgres + pgvector storage and search that the app
itself uses. No API server and no OpenAI are involved.

### Step 1: Quick run on 5 PDFs

```bash
scripts/local_pg_eval.sh --limit 5
```

The script does all of the following:

1. Checks that Ollama is running and `nomic-embed-text` is pulled.
2. Starts a dedicated Postgres + pgvector container (`docker-compose.eval.yml`, **port 5433**). It is
   separate from your dev database.
3. Runs the Alembic migrations, with a 768-size vector column for `nomic-embed-text`.
4. Creates the local user `rag-eval@example.com` and loads the PDFs once per parser. Each parser gets its
   own groups, e.g. `georgia_epd_admin_sops-pypdf` and `georgia_epd_admin_sops-docling`.
5. Runs `compare_parsers.py` and prints the results.

### Step 2: Full run on all PDFs

```bash
scripts/local_pg_eval.sh
```

Re-runs are safe: PDFs that are already loaded are skipped, so you can stop the script and run it again.

### Step 3 (optional): Chunks and a JSON report

```bash
COMPARE_ARGS="--show-chunks --report ~/pg_eval.json" scripts/local_pg_eval.sh
```

### Step 3b (optional): View the query run in Langfuse

Every query × parser becomes one Langfuse trace. You can open each one to see the query, the retrieved
chunks with their distances, and the scores.

1. Get API keys. The easiest way is a free Langfuse Cloud account at <https://cloud.langfuse.com>: create a
   project, then go to **Settings → API Keys → Create**. A self-hosted Langfuse works too; point
   `LANGFUSE_HOST` at it.
2. Put the keys in `.env.langfuse` in the project root. The file is gitignored:

   ```bash
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_HOST=https://cloud.langfuse.com      # or https://us.cloud.langfuse.com, or your own host
   ```

3. Run the eval as usual. Tracing turns on by itself when both keys are present:

   ```bash
   scripts/local_pg_eval.sh --limit 5
   ```

   The `comparing parsers` step prints `langfuse=on, session parser-eval-<timestamp>`. At the end it prints
   the trace count and a link to the first trace.

To run only the query step again, with your own session name:

```bash
# with the same exports as "Running the steps by hand" below, plus the keys from .env.langfuse
set -a; source .env.langfuse; set +a; export LANGFUSE_TRACING_ENABLED=true
uv run python scripts/compare_parsers.py --user-email rag-eval@example.com --run-name docling-vs-pypdf-v1
```

What you'll find in Langfuse:

| Where | What |
|---|---|
| **Sessions** → `parser-eval-…` (or your `--run-name`) | All traces from one run, together |
| **Traces**, filter by tag `pypdf` / `docling` | One parser's results |
| A trace's `pgvector_search` (retriever) span | The query, top_k, and the returned chunks (title, distance, first 500 characters) |
| A trace's **Scores** | `hit_at_1`, `hit_at_k`, `reciprocal_rank`, `top1_distance` |
| Trace metadata | parser, embedder, chunk size/overlap, group ids |
| **Dashboard / Scores**, grouped by tag | Average scores per parser across runs |

Use `--no-trace` to turn tracing off for one run. If the keys or host are wrong, the script prints
`langfuse auth failed … tracing off` and the comparison still runs.

### Other variations

```bash
PARSERS="pypdf" scripts/local_pg_eval.sh          # only one parser
scripts/local_pg_eval.sh --reset                  # wipe the eval DB first (required after changing the embedding model)
EVAL_USER_EMAIL=me@example.com scripts/local_pg_eval.sh
```

Any setting at the top of `scripts/local_pg_eval.sh` can be overridden through an environment variable,
e.g. `POSTGRES_PORT`, `RAG_EMBEDDER_MODEL` or `RAG_EMBEDDING_DIMENSIONS`.

### Step 4: Inspect or stop the database

You don't need `psql` installed on your Mac: use the one inside the container.

```bash
# interactive shell (quit with \q)
docker compose -f docker-compose.eval.yml -p rag-eval exec eval-db psql -U rag_eval -d rag_eval

# or, if you have psql locally (brew install libpq)
psql postgresql://rag_eval:rag_eval@localhost:5433/rag_eval
```

Tables: `user`, `group`, `groupmembership`, `document`, `documentchunk`, `alembic_version`, `session` and
`thread`. `user` and `group` are reserved words in SQL, so put them in double quotes.

Useful queries, run inside `psql`:

```sql
\dt                                   -- list tables
\d documentchunk                      -- columns (embedding is vector(768))

-- documents and chunks per parser group
SELECT g.name, count(DISTINCT d.id) AS docs, count(c.id) AS chunks
FROM "group" g
LEFT JOIN document d ON d.group_id = g.id
LEFT JOIN documentchunk c ON c.document_id = d.id
GROUP BY g.name;

-- the documents in one group
SELECT d.title, d.source FROM document d JOIN "group" g ON g.id = d.group_id
WHERE g.name = 'georgia_epd_admin_sops-docling' ORDER BY d.title;

-- compare the first chunk of the same PDF from each parser
SELECT g.name, left(c.content, 300) AS preview
FROM documentchunk c
JOIN document d ON d.id = c.document_id
JOIN "group" g ON g.id = d.group_id
WHERE d.title = 'sop-6-025-rev-2-control-chart-control-limits' AND c.chunk_index = 0;

-- chunk length stats per parser
SELECT g.name, round(avg(length(c.content))) AS avg_len, min(length(c.content)), max(length(c.content))
FROM documentchunk c JOIN document d ON d.id = c.document_id JOIN "group" g ON g.id = d.group_id
GROUP BY g.name;
```

Turn on `\x` for a vertical layout when the rows are wide. To run a single query without opening the
interactive shell:

```bash
docker compose -f docker-compose.eval.yml -p rag-eval exec eval-db \
  psql -U rag_eval -d rag_eval -c 'SELECT title, source FROM document LIMIT 10;'
```

Stop the database:

```bash
docker compose -f docker-compose.eval.yml -p rag-eval down      # stop it (keeps the data)
docker compose -f docker-compose.eval.yml -p rag-eval down -v   # stop it and delete the data
```

### Running the steps by hand

If you'd rather not use the driver script, export the same variables it sets, then run:

```bash
export APP_ENV=test POSTGRES_HOST=localhost POSTGRES_PORT=5433 \
  POSTGRES_DB=rag_eval POSTGRES_USER=rag_eval POSTGRES_PASSWORD=rag_eval \
  RAG_EMBEDDER_PROVIDER=ollama RAG_EMBEDDER_MODEL=nomic-embed-text RAG_EMBEDDING_DIMENSIONS=768 \
  RAG_EMBED_DOCUMENT_PREFIX="search_document: " RAG_EMBED_QUERY_PREFIX="search_query: " \
  LANGFUSE_TRACING_ENABLED=false DEBUG=false

docker compose -f docker-compose.eval.yml -p rag-eval up -d --wait
uv run alembic upgrade head
uv run python scripts/ingest_pdfs.py --user-email rag-eval@example.com --create-user --parser pypdf
uv run python scripts/ingest_pdfs.py --user-email rag-eval@example.com --parser docling --dry-run   # preview (needs the user to exist)
uv run python scripts/ingest_pdfs.py --user-email rag-eval@example.com --create-user --parser docling --dump-dir ~/parsed
uv run python scripts/compare_parsers.py --user-email rag-eval@example.com --show-chunks
```

---

## 4. Reading the results

Each run prints:

1. **Corpus stats** (option A) or an **ingest summary** (option B): characters, chunks and parse time per
   parser.
2. **Per-query table**: for each parser, the rank of the expected document (`#1` = top hit, `miss` = not in
   the top k), the best match's distance, and the top document.
3. **Summary table**:

| Metric | Meaning | Better |
|---|---|---|
| `hit@1` | Share of queries where the expected document is the top result | higher |
| `hit@k` | Share where it appears anywhere in the top k | higher |
| `MRR` | Average of 1/rank of the expected document | higher |
| `mean top-1 distance` | Cosine distance of the best chunk | lower |
| `mean top-k distance` | Average distance over the top k | lower |

Go by **hit@k and MRR**. Distances are only a rough signal, because docling's markdown changes where chunks
break.

---

## 5. Editing the test queries

The queries are in `scripts/parser_eval_queries.jsonl`, one JSON object per line. Lines starting with `#`
are comments:

```json
{"query": "How often are control charts generated?", "expected": "sop-6-025-rev-2-control-chart-control-limits"}
```

- `expected` is the PDF **file name without `.pdf`**. It can also be a list, if several documents count as
  correct.
- The 20 seed queries were drafted from the SOP titles. Replace them with real questions, especially ones
  whose answers are in **tables**, which is where docling should beat pypdf.
- With `--limit`, queries whose expected document wasn't loaded are skipped automatically.

### Conflict test (two documents that contradict each other)

`scripts/make_conflict_pdfs.py` generates two **fictional** Riverbend Environmental Laboratory documents in
`/Users/mw/Documents/AI/PDFS/conflict_test/`. They disagree on:

| Topic | `riverbend-sop-qa-101-rev-3-…` (2021) | `riverbend-field-guide-fg-07-…` (2024) |
|---|---|---|
| Nitrate holding time (table) | 48 hours | 7 days |
| Total metals holding time (table) | 6 months | 28 days |
| Storage temperature | ≤ 6 °C | ≤ 10 °C |
| Control limits | ±3 SD of 20 results | ±2 SD of 30 results |
| Who approves deviations | QA Manager, in writing | Laboratory Director, verbally |

Neither document says it replaces the other, so a good RAG system must retrieve **both** and flag the
conflict.

```bash
uv run scripts/make_conflict_pdfs.py          # (re)generate the PDFs; reportlab is installed on the fly
scripts/local_pg_eval.sh --limit 2            # conflict_test sorts first, so this ingests just these two
uv run python scripts/local_parser_eval.py --answer   # option A: see whether qwen flags the conflict
```

Conflict queries in `parser_eval_queries.jsonl` use `"match": "all"`: they count as a hit only when
**every** expected document is in the top k. They're kept out of hit@1 / hit@k / MRR and get their own rows
in the summary instead:

- `conflict: all docs in top-k`: the share of conflict queries where both documents were retrieved.
- `conflict: mean rank (found)`: the rank by which both had appeared. 2 is the best possible.

In Langfuse they carry the tag `conflict` and the score `all_conflicting_docs_retrieved`.

---

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `ollama not reachable` | Start Ollama (`ollama serve`) and check `curl localhost:11434/api/tags` |
| `missing ollama models` | `ollama pull nomic-embed-text` (and `ollama pull qwen3.5:0.8b` for `--answer`) |
| Docling crashes with `MPSNDArray ... unrecognized selector` | The Apple GPU (MPS) bug on macOS 14.5. The parser already forces CPU; make sure you're on the latest code |
| Docling is very slow | Expected on CPU. Use `--limit` for quick tests; results are cached after the first run |
| `no extractable text` for a PDF | It's probably scanned. Use `--ocr` with docling |
| `expected 768 dimensions, not 1536` (or similar) | The eval DB was created with a different embedding size. Run `scripts/local_pg_eval.sh --reset` |
| `langfuse auth failed … tracing off` | Check the keys and `LANGFUSE_HOST` in `.env.langfuse` (EU vs US cloud regions use different hosts) |
| Port 5433 already in use | `POSTGRES_PORT=5434 scripts/local_pg_eval.sh` |
| Results look stale after changing chunk settings or the model | Option A: `--no-cache`. Option B: `--reset` |
