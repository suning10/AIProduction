"""Bulk-ingest PDFs from a directory tree into the RAG knowledge base.

Walks ``--root`` recursively, parses every ``*.pdf`` with the chosen parser
(``app.services.document_parsers``), and ingests the text through
``app.services.rag.rag_service`` (the same chunk/embed/store path as
``POST /api/v1/rag/documents``), bypassing the HTTP layer and its rate limits.

Group mapping:
    * ``--group-id N``: every PDF goes into existing group N.
    * default: one group per top-level subfolder *and parser*, named
      ``<subfolder>-<parser>`` (e.g. ``georgia_epd_admin_sops-docling``), created
      on demand with ``--user-email`` as admin, or reused if that user already
      admins a group with that name. PDFs directly in ``--root`` use the root
      folder's name. Keeping each parser's output in its own groups is what lets
      ``scripts/compare_parsers.py`` evaluate them side by side.

Re-runs are idempotent: a PDF whose relative path is already stored as a
document ``source`` in the target group is skipped.

Usage:
    APP_ENV=development uv run python scripts/ingest_pdfs.py --user-email you@example.com --dry-run
    APP_ENV=development uv run python scripts/ingest_pdfs.py --user-email you@example.com --parser pypdf
    APP_ENV=development uv run python scripts/ingest_pdfs.py --user-email you@example.com --parser docling
"""

import argparse
import asyncio
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Set,
)

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from sqlmodel import (
    Session,
    col,
    select,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import logger  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.database import database_service  # noqa: E402
from app.services.document_parsers import (  # noqa: E402
    DocumentParser,
    get_parser,
    parser_names,
)
from app.services.group import group_service  # noqa: E402
from app.services.rag import rag_service  # noqa: E402
from parser_eval_common import quiet_noisy_loggers  # noqa: E402

DEFAULT_ROOT = "/Users/mw/Documents/AI/PDFS"

console = Console()


@dataclass
class IngestResult:
    """Outcome of ingesting a single PDF."""

    path: str
    group: str
    status: str
    chars: int = 0
    chunks: int = 0
    parse_seconds: float = 0.0
    detail: str = ""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Ingest a folder tree of PDFs into the RAG knowledge base.")
    parser.add_argument("--root", default=DEFAULT_ROOT, help=f"Root folder to scan (default: {DEFAULT_ROOT})")
    parser.add_argument("--user-email", required=True, help="Existing user who will own the documents")
    parser.add_argument("--parser", choices=parser_names(), default="pypdf", help="PDF parser (default: pypdf)")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR (docling only; for scanned PDFs, slow)")
    parser.add_argument("--group-id", type=int, default=None, help="Put all PDFs in this group instead of per-folder")
    parser.add_argument("--dump-dir", default=None, help="Also write parsed text to <dump-dir>/<parser>/<path>.md")
    parser.add_argument("--limit", type=int, default=None, help="Only ingest the first N PDFs (quick test)")
    parser.add_argument(
        "--create-user", action="store_true", help="Create --user-email (random password) if it doesn't exist"
    )
    parser.add_argument("--dry-run", action="store_true", help="List what would be ingested without writing")
    return parser.parse_args()


def group_name_for(pdf_path: Path, root: Path, parser_name: str) -> str:
    """Return ``<top-level subfolder or root name>-<parser>``."""
    relative = pdf_path.relative_to(root)
    folder = relative.parts[0] if len(relative.parts) > 1 else root.name
    return f"{folder}-{parser_name}"


async def resolve_group_id(name: str, user_id: int, cache: Dict[str, int]) -> int:
    """Find a group the user admins with this name, or create it."""
    if name in cache:
        return cache[name]

    for group, membership in await group_service.list_user_groups(user_id):
        if group.name == name and membership.role == "admin" and group.id is not None:
            cache[name] = group.id
            return group.id

    group = await group_service.create_group(name, user_id)
    if group.id is None:
        raise RuntimeError(f"group '{name}' was created without an id")
    console.print(f"[green]created group[/green] {name} (id={group.id})")
    cache[name] = group.id
    return group.id


def existing_sources(group_id: int) -> Set[str]:
    """Return the set of document sources already stored in a group."""
    with Session(database_service.engine) as session:
        statement = select(Document.source).where(col(Document.group_id) == group_id)
        return {s for s in session.exec(statement).all() if s}


def dump_text(dump_dir: Path, parser_name: str, source: str, text: str) -> None:
    """Write parsed text next to its siblings for manual diffing between parsers."""
    target = dump_dir / parser_name / f"{source}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


async def ingest_one(
    pdf_path: Path,
    root: Path,
    parser: DocumentParser,
    user_id: int,
    group_id: int,
    group_label: str,
    seen: Set[str],
    dump_dir: Optional[Path],
) -> IngestResult:
    """Parse and ingest one PDF, returning its outcome."""
    source = str(pdf_path.relative_to(root))
    if source in seen:
        return IngestResult(source, group_label, "skipped", detail="already ingested")

    started = time.perf_counter()
    try:
        text = await asyncio.to_thread(parser.parse, pdf_path)
    except Exception as e:
        logger.exception("pdf_parse_failed", path=source, parser=parser.name, error=str(e))
        return IngestResult(source, group_label, "failed", detail=f"parse: {e}")
    parse_seconds = time.perf_counter() - started

    if not text:
        return IngestResult(source, group_label, "failed", parse_seconds=parse_seconds, detail="no extractable text")

    if dump_dir is not None:
        await asyncio.to_thread(dump_text, dump_dir, parser.name, source, text)

    try:
        _, chunk_count = await rag_service.ingest_document(
            requesting_user_id=user_id,
            group_id=group_id,
            title=pdf_path.stem,
            content=text,
            source=source,
        )
    except Exception as e:
        logger.exception("pdf_ingest_failed", path=source, group_id=group_id, error=str(e))
        return IngestResult(source, group_label, "failed", len(text), parse_seconds=parse_seconds, detail=str(e))

    seen.add(source)
    return IngestResult(source, group_label, "ingested", len(text), chunk_count, parse_seconds)


def print_summary(results: List[IngestResult], parser_name: str) -> None:
    """Render a rich summary table of ingest outcomes."""
    table = Table(title=f"PDF ingest summary ({parser_name})")
    table.add_column("File")
    table.add_column("Group")
    table.add_column("Status")
    table.add_column("Chars", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Parse s", justify="right")
    table.add_column("Detail")

    styles = {"ingested": "green", "skipped": "yellow", "failed": "red", "would ingest": "cyan"}
    for r in results:
        table.add_row(
            r.path,
            r.group,
            f"[{styles.get(r.status, '')}]{r.status}",
            str(r.chars or ""),
            str(r.chunks or ""),
            f"{r.parse_seconds:.1f}" if r.parse_seconds else "",
            r.detail,
        )
    console.print(table)

    counts = {s: sum(1 for r in results if r.status == s) for s in styles}
    console.print(", ".join(f"{k}: {v}" for k, v in counts.items() if v))
    ingested = [r for r in results if r.status == "ingested"]
    if ingested:
        console.print(
            f"total chars: {sum(r.chars for r in ingested)}, chunks: {sum(r.chunks for r in ingested)}, "
            f"parse time: {sum(r.parse_seconds for r in ingested):.1f}s"
        )


async def main() -> int:
    """Run the bulk ingest."""
    quiet_noisy_loggers()
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        console.print(f"[red]root folder not found:[/red] {root}")
        return 1

    pdfs = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")[: args.limit]
    if not pdfs:
        console.print(f"[yellow]no PDFs found under[/yellow] {root}")
        return 0

    user = await database_service.get_user_by_email(args.user_email)
    if user is None and args.create_user and not args.dry_run:
        user = await database_service.create_user(args.user_email, User.hash_password(secrets.token_urlsafe(24)))
        console.print(f"[green]created user[/green] {args.user_email} (random password; for ingestion only)")
    if user is None or user.id is None:
        console.print(f"[red]user not found:[/red] {args.user_email}")
        return 1

    if args.group_id is not None and not await group_service.is_admin(user.id, args.group_id):
        console.print(f"[red]{args.user_email} is not an admin of group {args.group_id}[/red]")
        return 1

    console.print(f"found [bold]{len(pdfs)}[/bold] PDFs under {root}, parser=[bold]{args.parser}[/bold]")

    if args.dry_run:
        results = [
            IngestResult(
                str(p.relative_to(root)),
                str(args.group_id) if args.group_id is not None else group_name_for(p, root, args.parser),
                "would ingest",
            )
            for p in pdfs
        ]
        print_summary(results, args.parser)
        return 0

    parser = get_parser(args.parser, do_ocr=args.ocr)
    dump_dir = Path(args.dump_dir).expanduser().resolve() if args.dump_dir else None
    group_cache: Dict[str, int] = {}
    seen_by_group: Dict[int, Set[str]] = {}
    results: List[IngestResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("ingesting", total=len(pdfs))
        for pdf_path in pdfs:
            progress.update(task, description=pdf_path.name)

            group_label: str
            group_id: Optional[int] = args.group_id
            if group_id is None:
                group_label = group_name_for(pdf_path, root, parser.name)
                group_id = await resolve_group_id(group_label, user.id, group_cache)
            else:
                group_label = str(group_id)

            if group_id not in seen_by_group:
                seen_by_group[group_id] = existing_sources(group_id)

            results.append(
                await ingest_one(
                    pdf_path, root, parser, user.id, group_id, group_label, seen_by_group[group_id], dump_dir
                )
            )
            progress.advance(task)

    print_summary(results, parser.name)
    logger.info(
        "pdf_bulk_ingest_completed",
        root=str(root),
        parser=parser.name,
        total=len(results),
        failed=sum(1 for r in results if r.status == "failed"),
    )
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
