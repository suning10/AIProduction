"""LangGraph workflow that discovers, traces, explains and resolves NERP vs Synapse inventory gaps.

Shape — deterministic investigation, then a per-SKU resolver agent:

    discover_gaps ──Send per SKU/sloc──▶ investigate_sku ──▶ triage
        ├─ simple, fully explained SKUs ─▶ templated resolution (no LLM)
        └─ Send per remaining SKU ───────▶ resolve_sku (agent, tool: rag_search) ──▶ summarize ──▶ END

* ``investigate_sku`` is plain code (API calls + rules in ``inventory_analysis``):
  exact, cheap and repeatable across 100+ SKUs. It only asks the LLM for a
  hypothesis when the rules find no transaction-level discrepancy at all.
* ``resolve_sku`` is a small tool-calling agent with its own context — the
  SKU's compact finding, never raw transaction rows. Its only tool is the
  knowledge-base search, scoped to the requesting user and cached per query so
  many agents asking the same thing hit the vector store once. Tool rounds are
  capped by ``INVENTORY_RESOLVE_MAX_TOOL_ROUNDS``.
* ``summarize`` rolls the per-SKU resolutions up by root cause and writes the report.
* Parallelism is bounded by ``max_concurrency`` on the run config and by the
  client's HTTP semaphore, so neither the SCR API nor the LLM is flooded.
"""

import asyncio
import json
import time
from collections import defaultdict
from datetime import (
    date,
    timedelta,
)
from typing import (
    Any,
    Optional,
)

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import (
    END,
    StateGraph,
)
from langgraph.graph.state import (
    Command,
    CompiledStateGraph,
)
from langgraph.types import Send

from app.core.cache import (
    cache_key,
    cache_service,
)
from app.core.config import settings
from app.core.langgraph.tools.rag_search import rag_search
from app.core.logging import logger
from app.core.metrics import (
    inventory_sku_investigation_seconds,
    inventory_sku_resolutions_total,
    inventory_skus_investigated_total,
)
from app.core.observability import langfuse_callback_handler
from app.core.prompts import (
    INVENTORY_CLASSIFY_PROMPT,
    INVENTORY_RESOLVE_PROMPT,
    INVENTORY_SUMMARY_PROMPT,
)
from app.schemas.inventory import (
    Discrepancy,
    DiscrepancyKind,
    GapRecord,
    InventoryGapState,
    LlmClassification,
    RemediationPlan,
    ResolutionDraft,
    ResolutionMethod,
    RootCause,
    SkuFinding,
    SkuResolution,
)
from app.services.inventory_analysis import (
    classify,
    find_discrepancies,
    trace_gap_history,
)
from app.services.inventory_client import (
    InventoryClient,
    inventory_client,
)
from app.services.llm import llm_service
from app.services.rag import rag_service
from app.utils import extract_text_content

ROOT_CAUSE_LABELS: dict[RootCause, str] = {
    "missing_in_synapse": "Posted in NERP, missing in Synapse",
    "missing_in_nerp": "Recorded in Synapse, missing in NERP",
    "qty_mismatch": "Same reference, different quantity",
    "nerp_adjustment": "Adjustment only in NERP",
    "synapse_adjustment": "Adjustment only in Synapse",
    "timing_difference": "Timing / posting cutoff difference",
    "unexplained": "Unexplained",
    "error": "Investigation error",
}

# General procedure per discrepancy kind, used for templated (no-LLM) and fallback resolutions
TEMPLATE_PROCEDURES: dict[DiscrepancyKind, list[str]] = {
    "missing_in_synapse": [
        "Confirm the NERP document is valid (not reversed or posted in error).",
        "Have the 3PL record the matching transaction in Synapse, or reverse the NERP posting if the physical "
        "movement did not happen.",
    ],
    "missing_in_nerp": [
        "Confirm the Synapse transaction reflects a real physical movement.",
        "Post the matching goods movement in NERP, or have the 3PL reverse the Synapse transaction if it was "
        "recorded in error.",
    ],
    "qty_mismatch": [
        "Determine the correct quantity for the reference from the source document (ASN, pick ticket, receipt).",
        "Correct the system that holds the wrong quantity by the difference.",
    ],
    "nerp_adjustment": [
        "Confirm with inventory control why the NERP adjustment was posted.",
        "Mirror the adjustment in Synapse, or reverse it in NERP if it was posted in error.",
    ],
    "synapse_adjustment": [
        "Confirm with the 3PL why the Synapse adjustment or cycle count was recorded.",
        "Post the matching adjustment in NERP, or have the 3PL reverse it if it was recorded in error.",
    ],
}
VERIFY_ACTION = "Confirm the gap is closed on the next SCR report."

_MAX_EVIDENCE_SKUS = 10
_MAX_EVIDENCE_DISCREPANCIES = 5
_MAX_RESOLVER_DISCREPANCIES = 25
_NO_KB_ACCESS = "No knowledge base access for this run."
_KB_SEARCH_FAILED = "Knowledge base search failed; continue without it."


def _finding_from_gap(gap: GapRecord, **kwargs: Any) -> SkuFinding:
    return SkuFinding(
        sku=gap.sku,
        sloc=gap.sloc,
        description=gap.description,
        gap=gap.gap,
        abs_gap=gap.abs_gap,
        gap_value=gap.gap_value,
        **kwargs,
    )


def _merge_gaps(records: list[GapRecord]) -> list[GapRecord]:
    """Sum duplicate SKU/sloc rows (the report can split one SKU across stock categories)."""
    merged: dict[tuple[str, str], GapRecord] = {}
    for record in records:
        key = (record.sku, record.sloc)
        existing = merged.get(key)
        if existing is None:
            merged[key] = record.model_copy()
            continue
        existing.gap += record.gap
        existing.abs_gap += record.abs_gap
        existing.gap_value += record.gap_value
        existing.nerp_qty += record.nerp_qty
        existing.synapse_qty += record.synapse_qty
    return [g for g in merged.values() if g.gap != 0 or g.abs_gap != 0]


def _impact_key(finding: SkuFinding) -> float:
    return abs(finding.gap_value) or abs(finding.gap)


def _finding_evidence(finding: SkuFinding, max_discrepancies: int = _MAX_EVIDENCE_DISCREPANCIES) -> dict[str, Any]:
    """Compact, LLM-friendly view of a finding."""
    return {
        "sku": finding.sku,
        "sloc": finding.sloc,
        "description": finding.description,
        "net_gap": finding.gap,
        "gap_value": round(finding.gap_value, 2),
        "root_cause": finding.root_cause,
        "origin_date": finding.origin_date.isoformat() if finding.origin_date else None,
        "origin_before_lookback": finding.origin_truncated,
        "explained_qty": finding.explained_qty,
        "explained": finding.explained,
        "hypothesis": finding.hypothesis,
        "discrepancies": [
            d.model_dump(mode="json", exclude_none=True) for d in finding.discrepancies[:max_discrepancies]
        ],
        "more_discrepancies": max(0, len(finding.discrepancies) - max_discrepancies),
    }


def _resolver_input(finding: SkuFinding) -> dict[str, Any]:
    """Everything the resolver agent needs about one SKU — facts only, no raw transaction rows."""
    return {
        **_finding_evidence(finding, _MAX_RESOLVER_DISCREPANCIES),
        "root_cause_label": ROOT_CAUSE_LABELS[finding.root_cause],
        "reconciliation_window": [
            finding.window_start.isoformat() if finding.window_start else None,
            finding.window_end.isoformat() if finding.window_end else None,
        ],
        "gap_history": [c.model_dump(mode="json") for c in finding.changes],
    }


def is_simple(finding: SkuFinding) -> bool:
    """Fully explained by a few discrepancies of one kind — a template resolves it without the LLM."""
    limit = settings.INVENTORY_TEMPLATE_MAX_DISCREPANCIES
    return (
        finding.explained
        and 0 < len(finding.discrepancies) <= limit
        and len({d.kind for d in finding.discrepancies}) == 1
    )


def _template_action(d: Discrepancy) -> str:
    """One concrete action for a discrepancy, quoting only facts from the reconciliation."""
    when = d.txn_date.isoformat() if d.txn_date else "unknown date"
    ref = d.reference or "(no reference)"
    txn = f"{d.txn_type} " if d.txn_type else ""
    if d.kind == "missing_in_synapse":
        return f"Record {txn}{ref} ({when}, qty {d.nerp_qty}) in Synapse — it is posted in NERP only."
    if d.kind == "missing_in_nerp":
        return f"Post {txn}{ref} ({when}, qty {d.synapse_qty}) in NERP — it exists in Synapse only."
    if d.kind == "qty_mismatch":
        return (
            f"Reference {ref} ({txn}{when}): NERP qty {d.nerp_qty} vs Synapse qty {d.synapse_qty} — confirm the "
            f"correct quantity and correct the other system by {abs(d.impact)}."
        )
    if d.kind == "nerp_adjustment":
        return (
            f"NERP adjustment {txn}{ref} ({when}, qty {d.nerp_qty}) has no Synapse counterpart — mirror it in "
            "Synapse or reverse it in NERP."
        )
    return (
        f"Synapse adjustment {txn}{ref} ({when}, qty {d.synapse_qty}) has no NERP counterpart — post the "
        "matching adjustment in NERP or have the 3PL reverse it."
    )


def template_resolution(finding: SkuFinding, method: ResolutionMethod = "template") -> SkuResolution:
    """Deterministic resolution: used for simple SKUs, and as the fallback when the resolver agent fails."""
    kinds: list[DiscrepancyKind] = list(dict.fromkeys(d.kind for d in finding.discrepancies))
    procedure = [step for kind in kinds for step in TEMPLATE_PROCEDURES[kind]]
    actions = [_template_action(d) for d in finding.discrepancies]
    if not finding.explained:
        window = f"{finding.window_start} to {finding.window_end}"
        actions.append(
            f"Transaction differences explain {finding.explained_qty} of the {finding.gap} gap ({window}); "
            "investigate the remainder manually."
            + (f" Hypothesis: {finding.hypothesis}" if finding.hypothesis else "")
        )
    actions.append(VERIFY_ACTION)
    return SkuResolution(
        sku=finding.sku,
        sloc=finding.sloc,
        method=method,
        rationale=f"{ROOT_CAUSE_LABELS[finding.root_cause]}: explains {finding.explained_qty} of {finding.gap}.",
        actions=actions,
        procedure=procedure,
        confidence="high" if method == "template" else "low",
        needs_human_review=method != "template",
    )


def build_plans(findings: list[SkuFinding], resolutions: list[SkuResolution]) -> list[RemediationPlan]:
    """Roll per-SKU resolutions up into one plan per root cause.

    The plan's steps are the general procedure of the highest-impact SKU in the
    group (preferring a knowledge-base-grounded agent resolution).
    """
    by_key = {(r.sku, r.sloc): r for r in resolutions}
    groups: dict[RootCause, list[SkuFinding]] = defaultdict(list)
    for finding in findings:
        if finding.root_cause != "error":
            groups[finding.root_cause].append(finding)

    plans: list[RemediationPlan] = []
    for cause, items in groups.items():
        items.sort(key=_impact_key, reverse=True)
        resolved = [by_key[(f.sku, f.sloc)] for f in items if (f.sku, f.sloc) in by_key]
        lead = next((r for r in resolved if r.method == "agent" and r.procedure), None) or next(
            (r for r in resolved if r.procedure), None
        )
        review_count = sum(1 for r in resolved if r.needs_human_review)
        plans.append(
            RemediationPlan(
                root_cause=cause,
                sku_count=len(items),
                total_net_gap=sum(f.gap for f in items),
                total_abs_gap=sum(abs(f.gap) for f in items),
                skus=[f"{f.sku}@{f.sloc}" for f in items],
                steps=lead.procedure if lead else [],
                kb_sources=sorted({s for r in resolved for s in r.kb_sources}),
                needs_human_review=review_count > 0 or len(resolved) < len(items),
                review_count=review_count,
            )
        )
    return sorted(plans, key=lambda p: -p.total_abs_gap)


def _top_actions(findings: list[SkuFinding], resolutions: list[SkuResolution]) -> list[dict[str, Any]]:
    """Highest-impact SKUs with their concrete actions, for the report."""
    by_key = {(r.sku, r.sloc): r for r in resolutions}
    top = sorted((f for f in findings if (f.sku, f.sloc) in by_key), key=_impact_key, reverse=True)
    return [
        {
            "sku": f.sku,
            "sloc": f.sloc,
            "net_gap": f.gap,
            "gap_value": round(f.gap_value, 2),
            "root_cause": f.root_cause,
            "actions": by_key[(f.sku, f.sloc)].actions[:4],
            "needs_human_review": by_key[(f.sku, f.sloc)].needs_human_review,
        }
        for f in top[:_MAX_EVIDENCE_SKUS]
    ]


def _root_cause_stats(findings: list[SkuFinding]) -> list[dict[str, Any]]:
    buckets: dict[str, list[SkuFinding]] = defaultdict(list)
    for finding in findings:
        buckets[finding.root_cause].append(finding)
    stats = [
        {
            "root_cause": cause,
            "label": ROOT_CAUSE_LABELS.get(cause, cause),  # type: ignore[arg-type]
            "sku_count": len(items),
            "net_gap": sum(f.gap for f in items),
            "abs_gap": sum(abs(f.gap) for f in items),
            "gap_value": round(sum(f.gap_value for f in items), 2),
            "fully_explained": sum(1 for f in items if f.explained),
            "origin_before_lookback": sum(1 for f in items if f.origin_truncated),
        }
        for cause, items in buckets.items()
    ]
    return sorted(stats, key=lambda s: -s["abs_gap"])


def _fallback_report(
    state: InventoryGapState, stats: list[dict[str, Any]], plans: list[RemediationPlan], top: list[dict[str, Any]]
) -> str:
    """Deterministic Markdown report used when the summary LLM call fails."""
    explained = sum(1 for f in state.findings if f.explained)
    lines = [
        f"# Inventory gap investigation — {state.as_of}",
        "",
        f"{len(state.findings)} SKU/locations investigated"
        f"{' (truncated, ' + str(state.total_gaps) + ' had gaps)' if state.truncated else ''}; "
        f"{explained} fully explained by transaction differences.",
        "",
        "| Root cause | SKUs | Net gap | Abs gap | Fully explained |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {s['label']} | {s['sku_count']} | {s['net_gap']} | {s['abs_gap']} | {s['fully_explained']} |"
        for s in stats
    ]
    for plan in plans:
        lines += ["", f"## {ROOT_CAUSE_LABELS.get(plan.root_cause, plan.root_cause)}", ""]
        lines += [f"{i}. {step}" for i, step in enumerate(plan.steps, start=1)]
        if plan.review_count:
            lines += ["", f"{plan.review_count} SKU(s) need human review."]
    if top:
        lines += ["", "## Highest-impact SKUs", ""]
        for item in top:
            lines.append(f"- **{item['sku']} @ {item['sloc']}** (gap {item['net_gap']}):")
            lines += [f"  - {action}" for action in item["actions"]]
    return "\n".join(lines)


def _as_state(state: InventoryGapState | dict[str, Any]) -> InventoryGapState:
    """``Send`` payloads reach the target node as a raw dict, not the Pydantic state — coerce them."""
    return state if isinstance(state, InventoryGapState) else InventoryGapState.model_validate(state)


class InventoryGapAgent:
    """Runs the inventory gap investigation graph."""

    def __init__(self, client: InventoryClient = inventory_client):
        """Create the agent.

        Args:
            client: SCR API client; injectable for tests.
        """
        self._client = client
        self._graph: Optional[CompiledStateGraph] = None

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _discover_gaps(self, state: InventoryGapState, config: RunnableConfig) -> Command:
        """Collect SKU/slocs with a gap on the report date and fan out one branch per SKU."""
        if state.as_of is None:
            raise ValueError("as_of date is required")
        as_of = state.as_of

        slocs = state.locations or settings.INVENTORY_SLOCS
        if not slocs:
            summary = await self._client.get_sloc_summary(as_of)
            slocs = [s.sloc for s in summary if s.skus_with_gap > 0]
            logger.info("inventory_slocs_discovered", investigation_id=state.investigation_id, slocs=slocs)

        results = await asyncio.gather(*[self._client.get_gaps(as_of, sloc) for sloc in slocs], return_exceptions=True)
        records: list[GapRecord] = []
        error_findings: list[SkuFinding] = []
        for sloc, result in zip(slocs, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "inventory_gap_discovery_failed",
                    investigation_id=state.investigation_id,
                    sloc=sloc,
                    error=str(result),
                )
                error_findings.append(
                    SkuFinding(sku="*", sloc=sloc, gap=0, root_cause="error", error=f"gap report failed: {result}")
                )
                continue
            records.extend(result)

        gaps = sorted(_merge_gaps(records), key=lambda g: (abs(g.gap_value), abs(g.gap), g.abs_gap), reverse=True)
        truncated = len(gaps) > settings.INVENTORY_MAX_SKUS
        selected = gaps[: settings.INVENTORY_MAX_SKUS]
        logger.info(
            "inventory_gaps_discovered",
            investigation_id=state.investigation_id,
            sloc_count=len(slocs),
            gap_count=len(gaps),
            investigating=len(selected),
        )

        update = {"total_gaps": len(gaps), "truncated": truncated, "findings": error_findings}
        if not selected:
            return Command(update=update, goto="summarize")
        return Command(
            update=update,
            goto=[
                Send(
                    "investigate_sku",
                    {"current_gap": gap, "as_of": as_of, "investigation_id": state.investigation_id},
                )
                for gap in selected
            ],
        )

    async def _investigate_sku(self, state: InventoryGapState, config: RunnableConfig) -> Command:
        """Trace one SKU/sloc's gap origin, reconcile its transactions and classify the root cause."""
        state = _as_state(state)
        gap = state.current_gap
        if gap is None or state.as_of is None:
            raise ValueError("investigate_sku requires current_gap and as_of")

        started = time.perf_counter()
        try:
            finding = await self._investigate(gap, state.as_of)
        except Exception as e:
            logger.exception(
                "inventory_sku_investigation_failed",
                investigation_id=state.investigation_id,
                sku=gap.sku,
                sloc=gap.sloc,
            )
            finding = _finding_from_gap(gap, root_cause="error", error=str(e))

        inventory_sku_investigation_seconds.observe(time.perf_counter() - started)
        inventory_skus_investigated_total.labels(root_cause=finding.root_cause, explained=str(finding.explained)).inc()
        return Command(update={"findings": [finding]}, goto="triage")

    async def _investigate(self, gap: GapRecord, as_of: date) -> SkuFinding:
        points = await self._client.get_day_over_day(gap.sku, gap.sloc)
        history = trace_gap_history(points, as_of, settings.INVENTORY_LOOKBACK_DAYS)

        origin = history.origin_date or as_of
        window_start = origin - timedelta(days=settings.INVENTORY_RECON_PADDING_DAYS)
        data = await self._client.get_reconciliation_data(gap.sku, gap.sloc, window_start, as_of)

        discrepancies = find_discrepancies(data)
        root_cause, explained, explained_qty = classify(discrepancies, gap.gap)
        finding = _finding_from_gap(
            gap,
            origin_date=history.origin_date,
            origin_truncated=history.origin_truncated,
            window_start=window_start,
            window_end=as_of,
            changes=history.changes,
            discrepancies=discrepancies,
            explained_qty=explained_qty,
            root_cause=root_cause,
            explained=explained,
        )
        logger.debug(
            "inventory_sku_investigated",
            sku=gap.sku,
            sloc=gap.sloc,
            root_cause=root_cause,
            explained=explained,
            discrepancy_count=len(discrepancies),
        )

        if root_cause == "unexplained" and not explained and settings.INVENTORY_LLM_CLASSIFY_ENABLED:
            return await self._llm_classify(finding)
        return finding

    async def _llm_classify(self, finding: SkuFinding) -> SkuFinding:
        """Ask the LLM for a hypothesis when no transaction-level discrepancy was found."""
        evidence = {
            **_finding_evidence(finding),
            "reconciliation_window": [
                finding.window_start.isoformat() if finding.window_start else None,
                finding.window_end.isoformat() if finding.window_end else None,
            ],
            "gap_history": [c.model_dump(mode="json") for c in finding.changes],
        }
        try:
            verdict = await llm_service.call(
                [SystemMessage(content=INVENTORY_CLASSIFY_PROMPT), HumanMessage(content=json.dumps(evidence))],
                response_format=LlmClassification,
            )
        except Exception:
            logger.exception("inventory_llm_classify_failed", sku=finding.sku, sloc=finding.sloc)
            return finding

        root_cause: RootCause = verdict.root_cause if verdict.root_cause != "error" else "unexplained"
        return finding.model_copy(
            update={"root_cause": root_cause, "hypothesis": f"[{verdict.confidence} confidence] {verdict.hypothesis}"}
        )

    async def _triage(self, state: InventoryGapState, config: RunnableConfig) -> Command:
        """Template-resolve simple SKUs; fan out one resolver agent per remaining SKU."""
        simple: list[SkuFinding] = []
        complex_: list[SkuFinding] = []
        for finding in state.findings:
            if finding.root_cause == "error":
                continue
            (simple if is_simple(finding) else complex_).append(finding)

        resolutions = [template_resolution(f) for f in simple]
        if resolutions:
            inventory_sku_resolutions_total.labels(method="template", needs_review="False").inc(len(resolutions))
        logger.info(
            "inventory_findings_triaged",
            investigation_id=state.investigation_id,
            template_count=len(simple),
            agent_count=len(complex_),
        )

        update = {"resolutions": resolutions}
        if not complex_:
            return Command(update=update, goto="summarize")
        return Command(
            update=update,
            goto=[
                Send(
                    "resolve_sku",
                    {"current_finding": f, "investigation_id": state.investigation_id, "as_of": state.as_of},
                )
                for f in sorted(complex_, key=_impact_key, reverse=True)
            ],
        )

    async def _resolve_sku(self, state: InventoryGapState, config: RunnableConfig) -> Command:
        """Run the resolver agent for one SKU; fall back to a templated resolution on failure."""
        state = _as_state(state)
        finding = state.current_finding
        if finding is None:
            raise ValueError("resolve_sku requires current_finding")

        user_id = config.get("metadata", {}).get("user_id")
        try:
            resolution = await self._run_resolver(finding, user_id)
        except Exception:
            logger.exception(
                "inventory_sku_resolution_failed",
                investigation_id=state.investigation_id,
                sku=finding.sku,
                sloc=finding.sloc,
            )
            resolution = template_resolution(finding, method="fallback")

        inventory_sku_resolutions_total.labels(
            method=resolution.method, needs_review=str(resolution.needs_human_review)
        ).inc()
        return Command(update={"resolutions": [resolution]}, goto="summarize")

    async def _run_resolver(self, finding: SkuFinding, user_id: Optional[Any]) -> SkuResolution:
        """Tool-calling loop: the agent searches the knowledge base, then returns a structured resolution."""
        messages: list[BaseMessage] = [
            SystemMessage(content=INVENTORY_RESOLVE_PROMPT),
            HumanMessage(content=json.dumps(_resolver_input(finding), indent=1)),
        ]
        queries: list[str] = []
        retrieved_titles: set[str] = set()

        for _ in range(settings.INVENTORY_RESOLVE_MAX_TOOL_ROUNDS):
            response = await llm_service.call(messages, tools=[rag_search])
            tool_calls = response.tool_calls if isinstance(response, AIMessage) else []
            if not tool_calls:
                break
            messages.append(response)
            searches = [str(tc["args"].get("query", "")).strip() for tc in tool_calls]
            results = await asyncio.gather(*[self._search_kb(user_id, q) for q in searches])
            for tool_call, query, (text, titles) in zip(tool_calls, searches, results, strict=True):
                queries.append(query)
                retrieved_titles.update(titles)
                messages.append(ToolMessage(content=text, name=tool_call["name"], tool_call_id=tool_call["id"] or ""))

        messages.append(HumanMessage(content="Give your final resolution for this SKU now."))
        draft = await llm_service.call(messages, response_format=ResolutionDraft)

        # Only keep citations of documents the agent actually retrieved
        sources = [s for s in draft.kb_sources if s in retrieved_titles]
        logger.debug(
            "inventory_sku_resolved",
            sku=finding.sku,
            sloc=finding.sloc,
            query_count=len(queries),
            source_count=len(sources),
        )
        return SkuResolution(
            sku=finding.sku,
            sloc=finding.sloc,
            method="agent",
            rationale=draft.rationale,
            actions=draft.actions,
            procedure=draft.procedure,
            kb_sources=sources,
            kb_queries=queries,
            confidence=draft.confidence,
            needs_human_review=draft.needs_human_review or not sources or not finding.explained,
        )

    async def _search_kb(self, user_id: Optional[Any], query: str) -> tuple[str, list[str]]:
        """Knowledge-base search scoped to the requesting user, cached per query (non-empty hits only).

        Returns:
            tuple: Formatted excerpts for the agent, and the titles of the retrieved documents.
        """
        if user_id is None:
            return _NO_KB_ACCESS, []
        if not query:
            return "Empty query.", []

        key = cache_key("inventory_kb", str(user_id), query.lower())
        cached = await cache_service.get(key)
        if cached is not None:
            hit = json.loads(cached)
            return hit["text"], hit["titles"]

        try:
            results = await rag_service.search(int(user_id), query)
            text = await rag_service.format_results(results)
        except Exception:
            logger.exception("inventory_kb_search_failed", query=query)
            return _KB_SEARCH_FAILED, []

        titles = sorted({r.title for r in results})
        if results:
            await cache_service.set(
                key, json.dumps({"text": text, "titles": titles}), ttl=settings.INVENTORY_KB_CACHE_TTL_SECONDS
            )
        return text, titles

    async def _summarize(self, state: InventoryGapState, config: RunnableConfig) -> Command:
        """Roll resolutions up by root cause and write the final Markdown report."""
        stats = _root_cause_stats(state.findings)
        plans = build_plans(state.findings, state.resolutions)
        top = _top_actions(state.findings, state.resolutions)
        payload = {
            "report_date": state.as_of.isoformat() if state.as_of else None,
            "sku_locations_with_gap": state.total_gaps,
            "investigated": len(state.findings),
            "truncated_to_max_skus": state.truncated,
            "fully_explained": sum(1 for f in state.findings if f.explained),
            "needs_human_review": sum(1 for r in state.resolutions if r.needs_human_review),
            "root_causes": stats,
            "remediation_plans": [p.model_dump(mode="json", exclude={"skus"}) for p in plans],
            "top_actions": top,
            "errors": [{"sku": f.sku, "sloc": f.sloc, "error": f.error} for f in state.findings if f.error][:10],
        }
        try:
            response = await llm_service.call(
                [SystemMessage(content=INVENTORY_SUMMARY_PROMPT), HumanMessage(content=json.dumps(payload, indent=1))],
                tools=[],
            )
            report = extract_text_content(response.content) or _fallback_report(state, stats, plans, top)
        except Exception:
            logger.exception("inventory_summary_failed", investigation_id=state.investigation_id)
            report = _fallback_report(state, stats, plans, top)

        logger.info(
            "inventory_investigation_summarized",
            investigation_id=state.investigation_id,
            finding_count=len(state.findings),
            resolution_count=len(state.resolutions),
            plan_count=len(plans),
        )
        return Command(update={"report": report, "remediations": plans}, goto=END)

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------

    def get_graph(self) -> CompiledStateGraph:
        """Build (once) and return the compiled investigation graph.

        No checkpointer: results are persisted to the investigation tables, and
        a failed run is simply re-submitted.
        """
        if self._graph is None:
            builder = StateGraph(InventoryGapState)
            builder.add_node("discover_gaps", self._discover_gaps, destinations=("investigate_sku", "summarize"))
            builder.add_node("investigate_sku", self._investigate_sku, destinations=("triage",))
            builder.add_node("triage", self._triage, destinations=("resolve_sku", "summarize"))
            builder.add_node("resolve_sku", self._resolve_sku, destinations=("summarize",))
            builder.add_node("summarize", self._summarize, destinations=(END,))
            builder.set_entry_point("discover_gaps")
            self._graph = builder.compile(name=f"{settings.PROJECT_NAME} Inventory Gap Agent")
            logger.info("inventory_graph_created")
        return self._graph

    async def run(
        self,
        investigation_id: str,
        as_of: date,
        locations: Optional[list[str]] = None,
        user_id: Optional[int] = None,
    ) -> InventoryGapState:
        """Run a full investigation and return the final state.

        Args:
            investigation_id: Persisted investigation id (used for tracing/logging).
            as_of: Gap report date.
            locations: Storage locations to scan; all with gaps when omitted.
            user_id: Requesting user — scopes knowledge-base access.

        Returns:
            InventoryGapState: findings (each with its resolution), root-cause plans and the report.
        """
        callbacks: list[BaseCallbackHandler] = [langfuse_callback_handler] if settings.LANGFUSE_TRACING_ENABLED else []
        config: RunnableConfig = {
            "callbacks": callbacks,
            "max_concurrency": settings.INVENTORY_MAX_CONCURRENCY,
            "run_name": "inventory_gap_investigation",
            "metadata": {
                "user_id": user_id,
                "investigation_id": investigation_id,
                "langfuse_session_id": investigation_id,
                "environment": settings.ENVIRONMENT.value,
            },
        }
        result = await self.get_graph().ainvoke(
            {"investigation_id": investigation_id, "as_of": as_of, "locations": locations},
            config=config,
        )
        state = InventoryGapState.model_validate(result)
        by_key = {(r.sku, r.sloc): r for r in state.resolutions}
        state.findings = [f.model_copy(update={"resolution": by_key.get((f.sku, f.sloc))}) for f in state.findings]
        return state


inventory_gap_agent = InventoryGapAgent()
