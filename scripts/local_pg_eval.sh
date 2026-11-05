#!/usr/bin/env bash
# End-to-end parser comparison on the real pgvector path, fully local:
#   Docker: Postgres + pgvector only (docker-compose.eval.yml, port 5433)
#   Host:   Ollama for embeddings (nomic-embed-text, 768-dim); no API server, no OpenAI
#
# Steps: start DB → alembic migrate → ingest with each parser → compare_parsers.py
#
# Usage:
#   scripts/local_pg_eval.sh                       # all PDFs, pypdf + docling
#   scripts/local_pg_eval.sh --limit 5             # quick run (passed to ingest_pdfs.py)
#   PARSERS="pypdf" scripts/local_pg_eval.sh       # subset of parsers
#   COMPARE_ARGS="--show-chunks --report /tmp/pg_eval.json" scripts/local_pg_eval.sh
#   scripts/local_pg_eval.sh --reset               # drop the eval DB volume first (e.g. after changing the embedder)
#   Langfuse: create .env.langfuse with LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST to trace the query run
#
# Any setting below can be overridden from the environment.
set -euo pipefail

cd "$(dirname "$0")/.."

RESET=false
INGEST_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--reset" ]]; then RESET=true; else INGEST_ARGS+=("$arg"); fi
done

# APP_ENV=test has no .env.test, so the app reads only what's exported here.
export APP_ENV="${APP_ENV:-test}"
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5433}"
export POSTGRES_DB="${POSTGRES_DB:-rag_eval}"
export POSTGRES_USER="${POSTGRES_USER:-rag_eval}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-rag_eval}"
export RAG_EMBEDDER_PROVIDER="${RAG_EMBEDDER_PROVIDER:-ollama}"
export RAG_EMBEDDER_MODEL="${RAG_EMBEDDER_MODEL:-nomic-embed-text}"
export RAG_EMBEDDING_DIMENSIONS="${RAG_EMBEDDING_DIMENSIONS:-768}"
export RAG_EMBED_DOCUMENT_PREFIX="${RAG_EMBED_DOCUMENT_PREFIX-search_document: }"
export RAG_EMBED_QUERY_PREFIX="${RAG_EMBED_QUERY_PREFIX-search_query: }"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
# Langfuse (optional): put LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST in .env.langfuse
# (gitignored) or export them. Tracing turns on automatically when both keys are present.
LANGFUSE_ENV_FILE="${LANGFUSE_ENV_FILE:-.env.langfuse}"
if [[ -f "$LANGFUSE_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$LANGFUSE_ENV_FILE"
  set +a
fi
if [[ -n "${LANGFUSE_PUBLIC_KEY:-}" && -n "${LANGFUSE_SECRET_KEY:-}" ]]; then
  export LANGFUSE_TRACING_ENABLED="${LANGFUSE_TRACING_ENABLED:-true}"
else
  export LANGFUSE_TRACING_ENABLED=false
fi
# app logging keys off DEBUG (DEBUG→debug level, else info), not LOG_LEVEL
export DEBUG="${DEBUG:-false}"

EVAL_USER_EMAIL="${EVAL_USER_EMAIL:-rag-eval@example.com}"
PARSERS="${PARSERS:-pypdf docling}"
COMPARE_ARGS="${COMPARE_ARGS:-}"
COMPOSE=(docker compose -f docker-compose.eval.yml -p rag-eval)

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "checking ollama ($OLLAMA_BASE_URL, model $RAG_EMBEDDER_MODEL)"
if ! curl -fsS "$OLLAMA_BASE_URL/api/tags" | grep -q "\"$RAG_EMBEDDER_MODEL"; then
  echo "ollama not reachable or model missing: run 'ollama serve' and 'ollama pull $RAG_EMBEDDER_MODEL'" >&2
  exit 1
fi

if $RESET; then
  step "resetting eval database volume"
  "${COMPOSE[@]}" down -v
fi

step "starting postgres + pgvector (port $POSTGRES_PORT)"
"${COMPOSE[@]}" up -d --wait

step "running migrations (embedding dimension $RAG_EMBEDDING_DIMENSIONS)"
uv run alembic upgrade head

for parser in $PARSERS; do
  step "ingesting with $parser"
  # ingest exits non-zero if any single PDF failed; keep going so the comparison still runs.
  uv run python scripts/ingest_pdfs.py --user-email "$EVAL_USER_EMAIL" --create-user \
    --parser "$parser" ${INGEST_ARGS[@]+"${INGEST_ARGS[@]}"} || echo "warning: some PDFs failed with $parser"
done

step "comparing parsers (langfuse tracing: $LANGFUSE_TRACING_ENABLED)"
# shellcheck disable=SC2086
uv run python scripts/compare_parsers.py --user-email "$EVAL_USER_EMAIL" --parsers $PARSERS $COMPARE_ARGS

echo
echo "DB stays up for inspection: ${COMPOSE[*]} exec eval-db psql -U $POSTGRES_USER -d $POSTGRES_DB"
echo "stop it with: ${COMPOSE[*]} down   (add -v to delete its data)"
