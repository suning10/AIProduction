"""Unit tests for the deterministic inventory gap analysis."""

from datetime import (
    date,
    timedelta,
)

from app.schemas.inventory import (
    DayOverDayPoint,
    QtyMismatchRecord,
    ReconciliationData,
    TxnRecord,
)
from app.services.inventory_analysis import (
    cancel_matched_adjustments,
    classify,
    find_discrepancies,
    trace_gap_history,
)

AS_OF = date(2026, 11, 5)


def _history(*gaps: int) -> list[DayOverDayPoint]:
    """Gap values oldest -> newest, ending on AS_OF."""
    n = len(gaps)
    return [DayOverDayPoint(date=AS_OF - timedelta(days=n - 1 - i), gap=g) for i, g in enumerate(gaps)]


def test_origin_is_first_day_of_current_nonzero_run():
    """Origin is first day of current nonzero run."""
    history = trace_gap_history(_history(0, 3, 0, 0, 5, 5, 8), AS_OF, lookback_days=30)
    assert history.origin_date == AS_OF - timedelta(days=2)
    assert not history.origin_truncated
    assert [(c.date, c.delta) for c in history.changes] == [
        (AS_OF - timedelta(days=2), 5),
        (AS_OF, 3),
    ]


def test_no_gap_today_means_no_origin():
    """No gap today means no origin."""
    assert trace_gap_history(_history(0, 4, 0), AS_OF, lookback_days=30).origin_date is None


def test_gap_older_than_lookback_is_truncated():
    """Gap older than lookback is truncated."""
    history = trace_gap_history(_history(*([6] * 40)), AS_OF, lookback_days=10)
    assert history.origin_date == AS_OF - timedelta(days=10)
    assert history.origin_truncated
    assert history.changes == []


def test_duplicate_dates_are_summed_and_future_points_ignored():
    """Duplicate dates are summed and future points ignored."""
    points = [
        DayOverDayPoint(date=AS_OF, gap=2),
        DayOverDayPoint(date=AS_OF, gap=3),
        DayOverDayPoint(date=AS_OF - timedelta(days=1), gap=0),
        DayOverDayPoint(date=AS_OF + timedelta(days=1), gap=99),
    ]
    history = trace_gap_history(points, AS_OF, lookback_days=30)
    assert history.origin_date == AS_OF
    assert history.changes[0].abs_gap == 5


def test_upstream_string_formats_parse():
    """Upstream string formats parse."""
    point = DayOverDayPoint.model_validate({"date": "11/05/2026", "gap": "7.000"})
    assert point.date == AS_OF and point.gap == 7


def test_each_discrepancy_kind_has_the_right_sign():
    """Each discrepancy kind has the right sign."""
    data = ReconciliationData(
        qty_mismatches=[QtyMismatchRecord(reference="R1", nerp_qty=12, synapse_qty=10)],
        missing_in_synapse=[TxnRecord(reference="R2", qty=5)],
        missing_in_nerp=[TxnRecord(reference="R3", qty=4)],
        nerp_adjustments=[TxnRecord(qty=-2, txn_date=AS_OF)],
        synapse_adjustments=[TxnRecord(qty=7, txn_date=AS_OF)],
    )
    impacts = {d.kind: d.impact for d in find_discrepancies(data)}
    assert impacts == {
        "qty_mismatch": 2,
        "missing_in_synapse": 5,
        "missing_in_nerp": -4,
        "nerp_adjustment": -2,
        "synapse_adjustment": -7,
    }


def test_adjustments_booked_in_both_systems_cancel():
    """Adjustments booked in both systems cancel."""
    nerp = [TxnRecord(qty=-3, txn_date=AS_OF), TxnRecord(qty=4, txn_date=AS_OF)]
    synapse = [TxnRecord(qty=-3, txn_date=AS_OF - timedelta(days=1))]
    left_nerp, left_synapse = cancel_matched_adjustments(nerp, synapse)
    assert [r.qty for r in left_nerp] == [4]
    assert left_synapse == []


def test_classify_explained_partial_and_unexplained():
    """Classify explained partial and unexplained."""
    data = ReconciliationData(
        missing_in_synapse=[TxnRecord(reference="R2", qty=5)],
        qty_mismatches=[QtyMismatchRecord(reference="R1", nerp_qty=11, synapse_qty=10)],
    )
    discrepancies = find_discrepancies(data)

    assert classify(discrepancies, 6) == ("missing_in_synapse", True, 6)
    assert classify(discrepancies, 10) == ("missing_in_synapse", False, 6)
    assert classify([], 10) == ("unexplained", False, 0)
