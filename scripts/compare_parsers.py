"""Compare PDF parsers end to end by retrieval quality over the same queries.

Prerequisite: ingest the same corpus once per parser with ``scripts/ingest_pdfs.py``
(``--parser pypdf`` and ``--parser docling``), which stores each parser's output
in its own ``<subfolder>-<parser>`` groups. Chunking and embedding are identical
for both, so differences here come from parsing alone.

For every query in ``--queries`` (JSONL: ``{"query": "...", "expected": "<pdf stem>"}``;
``expected`` is optional), each parser's groups are searched with no distance
cutoff and the top-k chunks are scored:

    * hit@1 / hit@k: an expected document is the top hit / in the top k
    * MRR: mean reciprocal rank of the first expected-document hit
    * top-1 distance: cosine distance of the best chunk (lower = closer match)

Langfuse: when ``LANGFUSE_TRACING_ENABLED=true`` and the keys are set, every
query x parser becomes one trace (``parser_eval_query``) holding a retriever span
with the returned chunks, plus trace scores ``hit_at_1``, ``hit_at_k``,
``reciprocal_rank`` and ``top1_distance``. All traces of a run share one
session id (``--run-name``), and each is tagged with its parser, so you can
filter and compare them in the Langfuse UI. ``--no-trace`` turns it off.

Usage:
    APP_ENV=development uv run python scripts/compare_parsers.py --user-email you@example.com
    APP_ENV=development uv run python scripts/compare_parsers.py --user-email you@example.com \
        --show-chunks --report /tmp/parser_report.json
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
)

from langfuse import (
    Langfuse,
    get_client,
)
from rich.console import Console
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.logging import logger  # noqa: E402
from app.core.observability import langfuse_init  # noqa: E402
from app.schemas.rag import SearchResult  # noqa: E402
from app.services.database import database_service  # noqa: E402
from app.services.document_parsers import parser_names  # noqa: E402
from app.services.group import group_service  # noqa: E402
from app.services.rag import rag_service  # noqa: E402
from parser_eval_common import (  # noqa: E402
    DEFAULT_QUERIES,
    QueryCase,
    QueryOutcome,
    case_rank,
    filter_cases,
    load_queries,
    print_per_query,
    print_summary,
    quiet_noisy_loggers,
)

NO_CUTOFF = 2.0  # cosine distance never exceeds 2
CHUNK_PREVIEW_CHARS = 500

console = Console()


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Compare PDF parsers by end-to-end retrieval quality.")
    parser.add_argument("--user-email", required=True, help="User who owns/belongs to the per-parser groups")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES), help="JSONL file of {query, expected}")
    parser.add_argument("--parsers", nargs="+", default=parser_names(), choices=parser_names())
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--show-chunks", action="store_true", help="Print each parser's top chunk per query")
    parser.add_argument("--report", default=None, help="Write per-query results as JSON to this path")
    parser.add_argument("--no-trace", action="store_true", help="Disable Langfuse tracing even if configured")
    parser.add_argument(
        "--run-name", default=None, help="Langfuse session id for this run (default: parser-eval-<timestamp>)"
    )
    return parser.parse_args()


async def parser_group_ids(user_id: int, parser_name: str) -> List[int]:
    """Return IDs of the user's groups holding this parser's documents (``*-<parser>``)."""
    suffix = f"-{parser_name}"
    return [g.id for g, _ in await group_service.list_user_groups(user_id) if g.name.endswith(suffix) and g.id]


async def search_groups(user_id: int, query: str, group_ids: List[int], top_k: int) -> List[SearchResult]:
    """Search each group without a distance cutoff and merge into one global top-k."""
    per_group = await asyncio.gather(
        *(rag_service.search(user_id, query, group_id=gid, top_k=top_k, max_distance=NO_CUTOFF) for gid in group_ids)
    )
    merged = [r for results in per_group for r in results]
    return sorted(merged, key=lambda r: r.distance)[:top_k]


def build_outcome(case: QueryCase, parser_name: str, results: List[SearchResult]) -> QueryOutcome:
    """Score one parser's results for one query."""
    titles = [r.title for r in results]
    return QueryOutcome(
        query=case.query,
        parser=parser_name,
        expected=case.expected,
        titles=titles,
        distances=[r.distance for r in results],
        rank=case_rank(titles, case),
        top_chunk=results[0].content if results else "",
        require_all=case.require_all,
    )


def tracing_client(no_trace: bool) -> Optional[Langfuse]:
    """Return a Langfuse client if tracing is enabled and configured, else None."""
    if no_trace or not settings.LANGFUSE_TRACING_ENABLED:
        return None
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        console.print("[yellow]LANGFUSE_TRACING_ENABLED is true but the keys are missing; tracing off[/yellow]")
        return None
    langfuse_init()
    lf = get_client()
    try:
        authenticated = lf.auth_check()
    except Exception as e:
        logger.warning("langfuse_unreachable", host=settings.LANGFUSE_HOST, error=str(e))
        authenticated = False
    if not authenticated:
        console.print(
            f"[yellow]langfuse auth failed at {settings.LANGFUSE_HOST}; check keys/host. tracing off[/yellow]"
        )
        lf.shutdown()
        return None
    return lf


async def evaluate_traced(
    lf: Langfuse,
    run_id: str,
    user_id: int,
    case: QueryCase,
    parser_name: str,
    group_ids: List[int],
    top_k: int,
) -> tuple[QueryOutcome, str]:
    """Run one query for one parser inside a Langfuse trace and attach retrieval scores."""
    with lf.start_as_current_span(
        name="parser_eval_query",
        input={"query": case.query, "expected": case.expected, "match": "all" if case.require_all else "any"},
    ) as span:
        span.update_trace(
            name="parser_eval_query",
            session_id=run_id,
            tags=["parser-eval", parser_name] + (["conflict"] if case.require_all else []),
            metadata={
                "parser": parser_name,
                "top_k": top_k,
                "group_ids": group_ids,
                "embedder": f"{settings.RAG_EMBEDDER_PROVIDER}/{settings.RAG_EMBEDDER_MODEL}",
                "chunk_size": settings.RAG_CHUNK_SIZE,
                "chunk_overlap": settings.RAG_CHUNK_OVERLAP,
            },
        )
        with lf.start_as_current_observation(
            name="pgvector_search", as_type="retriever", input={"query": case.query, "top_k": top_k}
        ) as retriever:
            results = await search_groups(user_id, case.query, group_ids, top_k)
            retriever.update(
                output=[
                    {
                        "rank": i,
                        "title": r.title,
                        "distance": round(r.distance, 4),
                        "content": r.content[:CHUNK_PREVIEW_CHARS],
                    }
                    for i, r in enumerate(results, start=1)
                ]
            )

        outcome = build_outcome(case, parser_name, results)
        span.update(output={"rank": outcome.rank, "top_titles": outcome.titles, "distances": outcome.distances})
        if case.require_all:
            span.score_trace(name="all_conflicting_docs_retrieved", value=float(outcome.rank is not None))
        else:
            span.score_trace(name="hit_at_1", value=float(outcome.rank == 1), data_type="NUMERIC")
            span.score_trace(name="hit_at_k", value=float(outcome.rank is not None), data_type="NUMERIC")
            span.score_trace(name="reciprocal_rank", value=1 / outcome.rank if outcome.rank else 0.0)
        if outcome.distances:
            span.score_trace(name="top1_distance", value=outcome.distances[0])
        return outcome, span.trace_id


async def main() -> int:
    """Run the comparison."""
    quiet_noisy_loggers()
    args = parse_args()
    queries_path = Path(args.queries).expanduser()
    if not queries_path.is_file():
        console.print(f"[red]queries file not found:[/red] {queries_path}")
        return 1
    cases = load_queries(queries_path)
    if not cases:
        console.print("[red]no queries loaded[/red]")
        return 1

    user = await database_service.get_user_by_email(args.user_email)
    if user is None or user.id is None:
        console.print(f"[red]user not found:[/red] {args.user_email}")
        return 1

    groups_by_parser: Dict[str, List[int]] = {}
    for name in args.parsers:
        groups_by_parser[name] = await parser_group_ids(user.id, name)
        if not groups_by_parser[name]:
            console.print(f"[red]no '*-{name}' groups for {args.user_email}; run ingest_pdfs.py --parser {name}[/red]")
            return 1
    # Score only against documents every compared parser actually ingested (e.g. after --limit).
    group_titles: Dict[int, set[str]] = {}
    for d, _ in await rag_service.list_accessible_documents(user.id):
        group_titles.setdefault(d.group_id, set()).add(d.title)
    common_titles = set.intersection(
        *(set().union(*(group_titles.get(g, set()) for g in gids)) for gids in groups_by_parser.values())
    )
    cases = filter_cases(cases, common_titles, labeled_only=True)
    if not cases:
        console.print("[red]no queries' expected documents are ingested for all parsers[/red]")
        return 1
    lf = tracing_client(args.no_trace)
    run_id = args.run_name or time.strftime("parser-eval-%Y%m%d-%H%M%S")
    console.print(
        f"{len(cases)} queries, top_k={args.top_k}, groups: {groups_by_parser}, "
        f"langfuse={'on, session ' + run_id if lf else 'off'}"
    )

    outcomes: Dict[str, List[QueryOutcome]] = {name: [] for name in args.parsers}
    trace_ids: List[str] = []
    with console.status("searching...") as status:
        for i, case in enumerate(cases, start=1):
            status.update(f"query {i}/{len(cases)}")
            for name in args.parsers:
                if lf is not None:
                    outcome, trace_id = await evaluate_traced(
                        lf, run_id, user.id, case, name, groups_by_parser[name], args.top_k
                    )
                    trace_ids.append(trace_id)
                else:
                    results = await search_groups(user.id, case.query, groups_by_parser[name], args.top_k)
                    outcome = build_outcome(case, name, results)
                outcomes[name].append(outcome)

    print_per_query(console, cases, outcomes, args.parsers)
    print_summary(console, outcomes, args.parsers, args.top_k)

    if args.show_chunks:
        for i, case in enumerate(cases):
            console.rule(case.query)
            for name in args.parsers:
                o = outcomes[name][i]
                console.print(
                    Panel(o.top_chunk or "[dim]no result", title=f"{name}: {o.titles[0] if o.titles else '-'}")
                )

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.write_text(
            json.dumps({name: [asdict(o) for o in rows] for name, rows in outcomes.items()}, indent=2),
            encoding="utf-8",
        )
        console.print(f"report written to {report_path}")

    if lf is not None:
        lf.flush()
        console.print(
            f"langfuse: {len(trace_ids)} traces in session [bold]{run_id}[/bold] "
            f"(Sessions tab, or filter Traces by tag 'parser-eval')"
        )
        try:
            console.print(f"first trace: {lf.get_trace_url(trace_id=trace_ids[0])}")
        except Exception as e:
            logger.warning("langfuse_trace_url_failed", error=str(e))

    logger.info("parser_comparison_completed", parsers=args.parsers, query_count=len(cases), top_k=args.top_k)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
