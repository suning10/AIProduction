"""Shared query loading, scoring, and reporting for the parser comparison scripts.

Used by ``compare_parsers.py`` (app DB + OpenAI) and ``local_parser_eval.py``
(fully local, Ollama) so both score retrieval identically.
"""

import json
import logging
from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path
from statistics import mean
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from rich.console import Console
from rich.table import Table

DEFAULT_QUERIES = Path(__file__).resolve().parent / "parser_eval_queries.jsonl"
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "docling",
    "docling_core",
    "docling_ibm_models",
    "rapidocr",
    "urllib3",
    "asyncio",
)


def quiet_noisy_loggers() -> None:
    """Keep transport/model-loading DEBUG chatter (the app's dev logging level) out of script output."""
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


@dataclass
class QueryCase:
    """One evaluation query and the document(s) that should answer it."""

    query: str
    expected: List[str] = field(default_factory=list)
    # True for conflict tests: the query only counts as a hit once *every* expected
    # document is retrieved (e.g. two SOPs that contradict each other).
    require_all: bool = False


@dataclass
class QueryOutcome:
    """Retrieval (and optionally generation) outcome for one query under one parser."""

    query: str
    parser: str
    expected: List[str]
    titles: List[str]
    distances: List[float]
    rank: Optional[int]
    top_chunk: str
    answer: str = ""
    require_all: bool = False


def load_queries(path: Path) -> List[QueryCase]:
    """Load query cases from JSONL. ``#`` lines are comments.

    Each row: ``{"query": ..., "expected": <stem or list of stems>, "match": "any" | "all"}``.
    ``match`` defaults to ``any``; ``all`` marks a conflict test needing every expected doc.
    """
    cases: List[QueryCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = json.loads(line)
        expected = row.get("expected") or []
        cases.append(
            QueryCase(
                query=row["query"],
                expected=[expected] if isinstance(expected, str) else expected,
                require_all=row.get("match", "any") == "all",
            )
        )
    return cases


def filter_cases(cases: List[QueryCase], titles: Set[str], labeled_only: bool) -> List[QueryCase]:
    """Drop expected docs that aren't in the corpus (e.g. a ``--limit`` run).

    Args:
        cases: Loaded query cases.
        titles: Document titles (PDF stems) present in the corpus.
        labeled_only: Drop queries left with no expected document, so misses
            on absent docs don't count against a parser.
    """
    filtered: List[QueryCase] = []
    for c in cases:
        present = [e for e in c.expected if e in titles]
        if c.require_all and len(present) < len(c.expected):
            present = []  # a conflict test is meaningless unless every side of it is in the corpus
        filtered.append(QueryCase(query=c.query, expected=present, require_all=c.require_all))
    return [c for c in filtered if c.expected] if labeled_only else filtered


def first_relevant_rank(titles: List[str], expected: List[str]) -> Optional[int]:
    """1-based rank of the first chunk from an expected document, or None."""
    for rank, title in enumerate(titles, start=1):
        if title in expected:
            return rank
    return None


def case_rank(titles: List[str], case: QueryCase) -> Optional[int]:
    """Rank at which the case is satisfied.

    ``any``: first expected doc's rank. ``all``: the rank by which every expected
    doc has appeared (the worst of their first ranks), or None if any is missing.
    """
    if not case.require_all:
        return first_relevant_rank(titles, case.expected)
    ranks = [first_relevant_rank(titles, [e]) for e in case.expected]
    return None if any(r is None for r in ranks) else max(r for r in ranks if r is not None)


def print_per_query(
    console: Console, cases: List[QueryCase], outcomes: Dict[str, List[QueryOutcome]], parsers: List[str]
) -> None:
    """Render one row per query with each parser's expected-doc rank, top-1 distance, and top-1 doc."""
    table = Table(title="Per-query results (rank of expected doc / top-1 distance / top-1 doc)", show_lines=True)
    table.add_column("Query", max_width=40)  # "(all)" = conflict test: rank by which every expected doc appeared
    table.add_column("Expected", max_width=28)
    for name in parsers:
        table.add_column(name, max_width=36)

    for i, case in enumerate(cases):
        cells = []
        for name in parsers:
            o = outcomes[name][i]
            if not o.titles:
                cells.append("[red]no results")
                continue
            rank = "-" if not o.expected else (f"[green]#{o.rank}" if o.rank else "[red]miss")
            if o.require_all:
                rank += " [magenta](all)"
            cells.append(f"{rank}  d={o.distances[0]:.3f}\n[dim]{o.titles[0]}")
        table.add_row(case.query, ", ".join(case.expected) or "[dim]n/a", *cells)
    console.print(table)


def print_summary(console: Console, outcomes: Dict[str, List[QueryOutcome]], parsers: List[str], top_k: int) -> None:
    """Render aggregate retrieval metrics per parser."""
    table = Table(title="Parser comparison summary")
    table.add_column("Metric")
    for name in parsers:
        table.add_column(name, justify="right")

    def labeled(name: str) -> List[QueryOutcome]:
        # standard metrics: single-answer queries only ("all" ranks can never be #1)
        return [o for o in outcomes[name] if o.expected and not o.require_all]

    def conflict(name: str) -> List[QueryOutcome]:
        return [o for o in outcomes[name] if o.expected and o.require_all]

    def fmt(values: List[float]) -> str:
        return f"{mean(values):.3f}" if values else "n/a"

    rows = {
        "hit@1": [fmt([float(o.rank == 1) for o in labeled(n)]) for n in parsers],
        f"hit@{top_k}": [fmt([float(o.rank is not None) for o in labeled(n)]) for n in parsers],
        "MRR": [fmt([1 / o.rank if o.rank else 0.0 for o in labeled(n)]) for n in parsers],
        "mean top-1 distance": [fmt([o.distances[0] for o in outcomes[n] if o.distances]) for n in parsers],
        f"mean top-{top_k} distance": [fmt([mean(o.distances) for o in outcomes[n] if o.distances]) for n in parsers],
        "labeled queries": [str(len(labeled(n))) for n in parsers],
    }
    if any(conflict(n) for n in parsers):
        rows[f"conflict: all docs in top-{top_k}"] = [
            fmt([float(o.rank is not None) for o in conflict(n)]) for n in parsers
        ]
        rows["conflict: mean rank (found)"] = [fmt([float(o.rank) for o in conflict(n) if o.rank]) for n in parsers]
        rows["conflict queries"] = [str(len(conflict(n))) for n in parsers]
    for metric, values in rows.items():
        table.add_row(metric, *values)
    console.print(table)
