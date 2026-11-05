"""Fully local, end-to-end parser comparison: no Postgres, no app users/groups, no OpenAI.

Pipeline per parser (``app.services.document_parsers``):
    parse PDFs → chunk (same splitter settings as the app) → embed with Ollama
    → in-memory cosine search → (optional) answer with an Ollama chat model

Queries and scoring are shared with ``compare_parsers.py`` (``parser_eval_common``),
so results are directly comparable in shape. Parsed text and chunk embeddings are
cached under ``--cache-dir`` (keyed by parser / embed model / chunk settings), so
the slow docling pass only runs once; only successful parses/embeddings are cached.

Prerequisites:
    ollama serve
    ollama pull nomic-embed-text
    ollama pull qwen3.5:0.8b        # only needed with --answer

Usage:
    uv run python scripts/local_parser_eval.py --limit 5                 # quick smoke test on 5 PDFs
    uv run python scripts/local_parser_eval.py                           # full corpus, both parsers
    uv run python scripts/local_parser_eval.py --answer --show-chunks --report /tmp/local_eval.json
"""

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
from dataclasses import (
    asdict,
    dataclass,
)
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
)

import httpx
import numpy as np
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from langchain_ollama import (
    ChatOllama,
    OllamaEmbeddings,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ollama import ResponseError
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.logging import logger  # noqa: E402
from app.core.observability import (  # noqa: E402
    langfuse_callback_handler,
    langfuse_init,
)
from app.services.document_parsers import (  # noqa: E402
    DocumentParser,
    get_parser,
    parser_names,
)
from parser_eval_common import (  # noqa: E402
    DEFAULT_QUERIES,
    QueryOutcome,
    case_rank,
    filter_cases,
    load_queries,
    print_per_query,
    print_summary,
    quiet_noisy_loggers,
)

DEFAULT_ROOT = "/Users/mw/Documents/AI/PDFS"
DEFAULT_CACHE = Path.home() / ".cache" / "aiproduction" / "parser_eval"
OLLAMA_ERRORS = (ResponseError, httpx.HTTPError, ConnectionError)
ANSWER_PROMPT = (
    "Answer the question using only the provided excerpts from laboratory SOPs. "
    "If the excerpts don't contain the answer, say so. If excerpts from different documents disagree, "
    "say that they conflict and give each document's value. Be concise and cite the document title."
)

console = Console()


@dataclass
class ParseStat:
    """Per-parser corpus statistics."""

    parser: str
    docs: int = 0
    failed: int = 0
    chars: int = 0
    chunks: int = 0
    parse_seconds: float = 0.0
    cached: int = 0


@dataclass
class ChunkIndex:
    """In-memory vector index for one parser's chunks."""

    titles: List[str]
    texts: List[str]
    vectors: np.ndarray  # (n_chunks, dim), L2-normalized


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Local (Ollama) end-to-end comparison of PDF parsers.")
    p.add_argument("--root", default=DEFAULT_ROOT, help=f"PDF folder tree (default: {DEFAULT_ROOT})")
    p.add_argument("--parsers", nargs="+", default=parser_names(), choices=parser_names())
    p.add_argument("--queries", default=str(DEFAULT_QUERIES), help="JSONL of {query, expected}")
    p.add_argument("--limit", type=int, default=None, help="Only use the first N PDFs (quick test)")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--chunk-size", type=int, default=settings.RAG_CHUNK_SIZE)
    p.add_argument("--chunk-overlap", type=int, default=settings.RAG_CHUNK_OVERLAP)
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--llm-model", default="qwen3.5:0.8b")
    p.add_argument("--answer", action="store_true", help="Generate an answer per query/parser with --llm-model")
    p.add_argument("--ocr", action="store_true", help="Enable docling OCR (scanned PDFs; slow)")
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    p.add_argument("--no-cache", action="store_true", help="Ignore cached text/embeddings (still rewrites cache)")
    p.add_argument("--no-trace", action="store_true", help="Disable Langfuse tracing even if configured")
    p.add_argument("--show-chunks", action="store_true", help="Print each parser's top chunk per query")
    p.add_argument("--report", default=None, help="Write per-query results as JSON to this path")
    return p.parse_args()


def with_prefix(model: str, kind: str, texts: List[str]) -> List[str]:
    """Add nomic's task prefixes (``search_document:`` / ``search_query:``), which it needs for good retrieval."""
    if "nomic" not in model:
        return texts
    return [f"{kind}: {t}" for t in texts]


class LocalEmbedder:
    """Ollama embeddings with tenacity retries and model-specific prefixes."""

    def __init__(self, model: str, base_url: str):
        """Create the Ollama embeddings client."""
        self.model = model
        self._client = OllamaEmbeddings(model=model, base_url=base_url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OLLAMA_ERRORS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def embed_documents(self, texts: List[str]) -> np.ndarray:
        """Embed chunks; returns L2-normalized vectors."""
        vectors = await self._client.aembed_documents(with_prefix(self.model, "search_document", texts))
        return normalize(np.asarray(vectors, dtype=np.float32))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OLLAMA_ERRORS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def embed_query(self, text: str) -> np.ndarray:
        """Embed a query; returns an L2-normalized vector."""
        vector = await self._client.aembed_query(with_prefix(self.model, "search_query", [text])[0])
        return normalize(np.asarray([vector], dtype=np.float32))[0]


def normalize(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize rows so a dot product is cosine similarity."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def check_ollama(base_url: str, models: List[str]) -> Optional[str]:
    """Return an error message if Ollama is unreachable or a model isn't pulled, else None."""
    try:
        response = httpx.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
    except httpx.HTTPError as e:
        return f"ollama not reachable at {base_url} ({e}); run `ollama serve`"
    available = {m["name"] for m in response.json().get("models", [])}
    available |= {name.split(":")[0] for name in available if name.endswith(":latest")}
    missing = [m for m in models if m not in available]
    return f"missing ollama models {missing}; run `ollama pull <model>`" if missing else None


def text_cache_path(cache_dir: Path, parser_name: str, source: str, ocr: bool) -> Path:
    """Where a parsed document's text is cached."""
    variant = f"{parser_name}-ocr" if ocr else parser_name
    return cache_dir / "text" / variant / f"{source}.md"


def embedding_cache_path(cache_dir: Path, model: str, chunks: List[str]) -> Path:
    """Where a document's chunk embeddings are cached, keyed by model and exact chunk contents."""
    digest = hashlib.sha256("\x00".join(chunks).encode("utf-8")).hexdigest()
    return cache_dir / "embeddings" / model.replace(":", "_").replace("/", "_") / f"{digest}.npy"


async def parse_with_cache(
    parser: DocumentParser, pdf: Path, source: str, cache_dir: Path, ocr: bool, use_cache: bool, stat: ParseStat
) -> Optional[str]:
    """Parse a PDF, reusing cached text when available. Returns None on failure."""
    cached = text_cache_path(cache_dir, parser.name, source, ocr)
    if use_cache and cached.is_file():
        stat.cached += 1
        return cached.read_text(encoding="utf-8")

    started = time.perf_counter()
    try:
        text = await asyncio.to_thread(parser.parse, pdf)
    except Exception as e:
        logger.exception("local_eval_parse_failed", parser=parser.name, path=source, error=str(e))
        return None
    stat.parse_seconds += time.perf_counter() - started

    if not text:
        logger.warning("local_eval_no_text", parser=parser.name, path=source)
        return None

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text


async def embed_with_cache(embedder: LocalEmbedder, chunks: List[str], cache_dir: Path, use_cache: bool) -> np.ndarray:
    """Embed a document's chunks, reusing cached vectors when the exact chunks were embedded before."""
    cached = embedding_cache_path(cache_dir, embedder.model, chunks)
    if use_cache and cached.is_file():
        return np.load(cached)

    vectors = await embedder.embed_documents(chunks)
    cached.parent.mkdir(parents=True, exist_ok=True)
    np.save(cached, vectors)
    return vectors


async def build_index(
    parser: DocumentParser,
    pdfs: List[Path],
    root: Path,
    splitter: RecursiveCharacterTextSplitter,
    embedder: LocalEmbedder,
    args: argparse.Namespace,
) -> tuple[ChunkIndex, ParseStat]:
    """Parse, chunk, and embed the corpus with one parser."""
    cache_dir = Path(args.cache_dir).expanduser()
    stat = ParseStat(parser=parser.name)
    titles: List[str] = []
    texts: List[str] = []
    blocks: List[np.ndarray] = []

    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold]{parser.name}[/bold] " + "{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("", total=len(pdfs))
        for pdf in pdfs:
            source = str(pdf.relative_to(root))
            progress.update(task, description=pdf.name)

            text = await parse_with_cache(parser, pdf, source, cache_dir, args.ocr, not args.no_cache, stat)
            if text is None:
                stat.failed += 1
                progress.advance(task)
                continue

            chunks = splitter.split_text(text)
            if chunks:
                blocks.append(await embed_with_cache(embedder, chunks, cache_dir, not args.no_cache))
                titles.extend([pdf.stem] * len(chunks))
                texts.extend(chunks)

            stat.docs += 1
            stat.chars += len(text)
            stat.chunks += len(chunks)
            progress.advance(task)

    vectors = np.vstack(blocks) if blocks else np.zeros((0, 1), dtype=np.float32)
    return ChunkIndex(titles=titles, texts=texts, vectors=vectors), stat


def search(index: ChunkIndex, query_vector: np.ndarray, top_k: int) -> List[tuple[str, str, float]]:
    """Return ``(title, chunk, cosine_distance)`` for the top-k chunks."""
    if not index.texts:
        return []
    distances = 1.0 - index.vectors @ query_vector
    order = np.argsort(distances)[:top_k]
    return [(index.titles[i], index.texts[i], float(distances[i])) for i in order]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OLLAMA_ERRORS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def answer_query(
    llm: ChatOllama, query: str, hits: List[tuple[str, str, float]], callbacks: List[BaseCallbackHandler], parser: str
) -> str:
    """Answer ``query`` from the retrieved chunks with the local chat model."""
    context = "\n\n".join(f"[{title}]\n{chunk}" for title, chunk, _ in hits)
    response = await llm.ainvoke(
        [SystemMessage(content=ANSWER_PROMPT), HumanMessage(content=f"Excerpts:\n{context}\n\nQuestion: {query}")],
        config={"callbacks": callbacks, "metadata": {"parser": parser, "eval": "local_parser_eval"}},
    )
    return str(response.content).strip()


def print_corpus_stats(stats: List[ParseStat]) -> None:
    """Render per-parser parsing/chunking statistics."""
    table = Table(title="Corpus stats per parser")
    for column in ("Parser", "Docs", "Failed", "Chars", "Chunks", "Avg chunk chars", "Parse s (uncached)", "Cached"):
        table.add_column(column, justify="left" if column == "Parser" else "right")
    for s in stats:
        avg = f"{s.chars / s.chunks:.0f}" if s.chunks else "-"
        table.add_row(
            s.parser,
            str(s.docs),
            str(s.failed),
            str(s.chars),
            str(s.chunks),
            avg,
            f"{s.parse_seconds:.1f}",
            str(s.cached),
        )
    console.print(table)


async def main() -> int:
    """Run the local end-to-end comparison."""
    quiet_noisy_loggers()
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        console.print(f"[red]root folder not found:[/red] {root}")
        return 1

    queries_path = Path(args.queries).expanduser()
    if not queries_path.is_file():
        console.print(f"[red]queries file not found:[/red] {queries_path}")
        return 1

    required_models = [args.embed_model] + ([args.llm_model] if args.answer else [])
    ollama_error = check_ollama(args.ollama_url, required_models)
    if ollama_error:
        console.print(f"[red]{ollama_error}[/red]")
        return 1

    pdfs = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")[: args.limit]
    if not pdfs:
        console.print(f"[yellow]no PDFs found under[/yellow] {root}")
        return 0

    cases = filter_cases(load_queries(queries_path), {p.stem for p in pdfs}, labeled_only=bool(args.limit))
    if not cases:
        console.print("[red]no queries apply to the selected PDFs (try without --limit)[/red]")
        return 1

    tracing = settings.LANGFUSE_TRACING_ENABLED and bool(settings.LANGFUSE_PUBLIC_KEY) and not args.no_trace
    callbacks: List[BaseCallbackHandler] = [langfuse_callback_handler] if tracing else []
    if tracing:
        langfuse_init()

    console.print(
        f"[bold]{len(pdfs)}[/bold] PDFs, [bold]{len(cases)}[/bold] queries, parsers={args.parsers}, "
        f"embed={args.embed_model}, chunk={args.chunk_size}/{args.chunk_overlap}, top_k={args.top_k}, "
        f"llm={args.llm_model if args.answer else 'off'}, langfuse={'on' if tracing else 'off'}"
    )

    splitter = RecursiveCharacterTextSplitter(chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    embedder = LocalEmbedder(args.embed_model, args.ollama_url)

    indexes: Dict[str, ChunkIndex] = {}
    stats: List[ParseStat] = []
    for name in args.parsers:
        indexes[name], stat = await build_index(
            get_parser(name, do_ocr=args.ocr), pdfs, root, splitter, embedder, args
        )
        stats.append(stat)
    print_corpus_stats(stats)

    llm = ChatOllama(model=args.llm_model, base_url=args.ollama_url, temperature=0, reasoning=False)
    outcomes: Dict[str, List[QueryOutcome]] = {name: [] for name in args.parsers}
    with console.status("querying...") as status:
        for i, case in enumerate(cases, start=1):
            status.update(f"query {i}/{len(cases)}")
            query_vector = await embedder.embed_query(case.query)
            for name in args.parsers:
                hits = search(indexes[name], query_vector, args.top_k)
                titles = [title for title, _, _ in hits]
                answer = await answer_query(llm, case.query, hits, callbacks, name) if args.answer and hits else ""
                outcomes[name].append(
                    QueryOutcome(
                        query=case.query,
                        parser=name,
                        expected=case.expected,
                        titles=titles,
                        distances=[d for _, _, d in hits],
                        rank=case_rank(titles, case),
                        top_chunk=hits[0][1] if hits else "",
                        answer=answer,
                        require_all=case.require_all,
                    )
                )

    print_per_query(console, cases, outcomes, args.parsers)
    print_summary(console, outcomes, args.parsers, args.top_k)

    if args.show_chunks or args.answer:
        for i, case in enumerate(cases):
            console.rule(case.query)
            for name in args.parsers:
                o = outcomes[name][i]
                if args.show_chunks:
                    title = f"{name} top chunk: {o.titles[0] if o.titles else '-'}"
                    console.print(Panel(o.top_chunk or "[dim]no result", title=title))
                if args.answer:
                    console.print(Panel(o.answer or "[dim]no answer", title=f"{name} answer", border_style="green"))

    if args.report:
        report_path = Path(args.report).expanduser()
        report = {
            "config": {k: v for k, v in vars(args).items() if k != "report"},
            "stats": [asdict(s) for s in stats],
            "results": {name: [asdict(o) for o in rows] for name, rows in outcomes.items()},
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        console.print(f"report written to {report_path}")

    logger.info("local_parser_eval_completed", parsers=args.parsers, pdf_count=len(pdfs), query_count=len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
