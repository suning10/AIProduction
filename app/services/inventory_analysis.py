"""Deterministic gap analysis: origin tracing, transaction reconciliation and root-cause rules.

Pure functions with no I/O — the LLM is only consulted (elsewhere) when these
rules can't account for a gap. Sign convention: ``gap = NERP - Synapse``.
"""

from collections import defaultdict
from datetime import (
    date,
    timedelta,
)

from app.schemas.inventory import (
    DayOverDayPoint,
    Discrepancy,
    DiscrepancyKind,
    GapChange,
    GapHistory,
    ReconciliationData,
    RootCause,
    TxnRecord,
)


def trace_gap_history(points: list[DayOverDayPoint], as_of: date, lookback_days: int) -> GapHistory:
    """Find when the current gap started and every day-over-day change since.

    Walks back from ``as_of`` through the contiguous run of non-zero gap days
    (within ``lookback_days``). The earliest day of that run is the origin.
    Duplicate rows for the same date (e.g. split stock categories) are summed.

    Args:
        points: Daily absolute-gap history, any order.
        as_of: The report date being investigated; later points are ignored.
        lookback_days: How far back to search for the origin.

    Returns:
        GapHistory: origin date (``None`` if the history shows no gap at all),
            whether the run hit the lookback limit, and the per-day changes.
    """
    window_start = as_of - timedelta(days=lookback_days)
    by_day: dict[date, int] = defaultdict(int)
    for point in points:
        if window_start <= point.date <= as_of:
            by_day[point.date] += abs(point.gap)

    days = sorted(by_day)
    if not days or by_day[days[-1]] == 0:
        return GapHistory()

    run: list[date] = []
    for day in reversed(days):
        if by_day[day] == 0:
            break
        run.append(day)
    run.reverse()

    # The run reaches the oldest day we can see, so the gap may have started earlier.
    truncated = run[0] == days[0]
    changes: list[GapChange] = []
    previous = by_day[run[0]] if truncated else 0
    for i, day in enumerate(run):
        if i == 0 and truncated:
            continue
        delta = by_day[day] - previous
        if delta != 0:
            changes.append(GapChange(date=day, abs_gap=by_day[day], delta=delta))
        previous = by_day[day]

    return GapHistory(origin_date=run[0], origin_truncated=truncated, changes=changes)


def _one_sided(records: list[TxnRecord], kind: DiscrepancyKind, side: str) -> list[Discrepancy]:
    """Transactions present on only one system: NERP-side adds to the gap, Synapse-side subtracts."""
    sign = 1 if side == "nerp" else -1
    return [
        Discrepancy(
            kind=kind,
            reference=r.reference,
            txn_type=r.txn_type,
            txn_date=r.txn_date,
            nerp_qty=r.qty if side == "nerp" else None,
            synapse_qty=r.qty if side == "synapse" else None,
            impact=sign * r.qty,
        )
        for r in records
        if r.qty != 0
    ]


def cancel_matched_adjustments(
    nerp: list[TxnRecord], synapse: list[TxnRecord], max_day_gap: int = 1
) -> tuple[list[TxnRecord], list[TxnRecord]]:
    """Drop unreferenced adjustment pairs booked in both systems (same qty, within ``max_day_gap`` days).

    Adjustments have no shared reference, so a count correction made in both
    systems shows up on both lists; only the unmatched remainder can cause a gap.
    """
    remaining_synapse = list(synapse)
    unmatched_nerp: list[TxnRecord] = []
    for adj in nerp:
        match = next(
            (
                s
                for s in remaining_synapse
                if s.qty == adj.qty
                and (
                    s.txn_date is None or adj.txn_date is None or abs((s.txn_date - adj.txn_date).days) <= max_day_gap
                )
            ),
            None,
        )
        if match is None:
            unmatched_nerp.append(adj)
        else:
            remaining_synapse.remove(match)
    return unmatched_nerp, remaining_synapse


def find_discrepancies(data: ReconciliationData) -> list[Discrepancy]:
    """Turn raw reconciliation records into signed discrepancies."""
    discrepancies = [
        Discrepancy(
            kind="qty_mismatch",
            reference=m.reference,
            txn_type=m.txn_type,
            txn_date=m.txn_date,
            nerp_qty=m.nerp_qty,
            synapse_qty=m.synapse_qty,
            impact=m.nerp_qty - m.synapse_qty,
        )
        for m in data.qty_mismatches
        if m.nerp_qty != m.synapse_qty
    ]
    discrepancies += _one_sided(data.missing_in_synapse, "missing_in_synapse", "nerp")
    discrepancies += _one_sided(data.missing_in_nerp, "missing_in_nerp", "synapse")

    nerp_adj, synapse_adj = cancel_matched_adjustments(data.nerp_adjustments, data.synapse_adjustments)
    discrepancies += _one_sided(nerp_adj, "nerp_adjustment", "nerp")
    discrepancies += _one_sided(synapse_adj, "synapse_adjustment", "synapse")

    discrepancies.sort(key=lambda d: (d.txn_date or date.min, d.kind))
    return discrepancies


def classify(discrepancies: list[Discrepancy], net_gap: int) -> tuple[RootCause, bool, int]:
    """Pick a root cause and decide whether the discrepancies account for the gap.

    Args:
        discrepancies: Signed discrepancies found in the reconciliation window.
        net_gap: The SKU's reported net gap (NERP - Synapse).

    Returns:
        tuple: ``(root_cause, explained, explained_qty)``. The root cause is the
            discrepancy kind with the largest total absolute impact, or
            ``"unexplained"`` when none were found. ``explained`` is true only
            when the impacts sum exactly to ``net_gap``.
    """
    explained_qty = sum(d.impact for d in discrepancies)
    if not discrepancies:
        return "unexplained", net_gap == 0, 0

    weight: dict[DiscrepancyKind, int] = defaultdict(int)
    for d in discrepancies:
        weight[d.kind] += abs(d.impact)
    root_cause: RootCause = max(weight, key=lambda k: weight[k])
    return root_cause, explained_qty == net_gap, explained_qty
