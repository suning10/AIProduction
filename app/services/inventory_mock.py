"""In-process fake of the EcomToolBox SCR APIs (``/admin/scr/*``) for development and tests.

Responses mirror the Java controller's JSON exactly — ``Result{code, msg, data}``
envelopes, camelCase entity fields, numbers as strings, ``MM/dd/yyyy`` dates — so
mock mode exercises the same config-driven mapping as the real API.

Each SKU/sloc gets a deterministic scenario (seeded by its key): a list of
gap-causing events dated relative to today. The gap report, day-over-day
history and transaction endpoints are all derived from those events, so they
stay mutually consistent and the agent's reconciliation should balance.
"""

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timedelta,
)
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import settings

MOCK_SLOCS = ("WR2E", "WR1A", "WR3C")
_HISTORY_DAYS = 20
_KINDS = (
    "missing_in_synapse",
    "missing_in_nerp",
    "qty_mismatch",
    "nerp_adjustment",
    "synapse_adjustment",
    "mixed",
    "unexplained",
)


@dataclass(frozen=True)
class _Event:
    days_ago: int
    kind: str
    impact: int  # contribution to NERP - Synapse
    reference: str

    @property
    def day(self) -> date:
        return date.today() - timedelta(days=self.days_ago)


@dataclass(frozen=True)
class _Scenario:
    sku: str
    sloc: str
    events: tuple[_Event, ...]
    noise_adjustment_days_ago: int | None  # a matched NERP+Synapse adjustment pair that must cancel out


def _rng(*parts: str) -> random.Random:
    seed = int(hashlib.sha256(":".join(parts).encode()).hexdigest()[:12], 16)
    return random.Random(seed)


@lru_cache(maxsize=1)
def _universe(sku_count: int) -> tuple[_Scenario, ...]:
    scenarios: list[_Scenario] = []
    for i in range(sku_count):
        sku = f"{100000 + i * 7}"
        for sloc_idx, sloc in enumerate(MOCK_SLOCS):
            rng = _rng(sku, sloc)
            if (i + sloc_idx) % 5 == 4:  # some SKU/slocs are clean
                scenarios.append(_Scenario(sku, sloc, (), None))
                continue
            kind = _KINDS[(i + sloc_idx) % len(_KINDS)]
            kinds = rng.sample(_KINDS[:5], 2) if kind == "mixed" else [kind]
            events: list[_Event] = []
            for n, k in enumerate(kinds):
                magnitude = rng.randint(1, 24)
                events.append(
                    _Event(
                        days_ago=rng.randint(1, 12),
                        kind=k,
                        impact=magnitude if rng.random() < 0.5 else -magnitude,
                        reference=f"{4500000000 + rng.randint(0, 99999999)}{n}",
                    )
                )
            noise = rng.randint(1, 12) if i % 3 == 0 else None
            scenarios.append(_Scenario(sku, sloc, tuple(events), noise))
    return tuple(scenarios)


def _scenarios() -> tuple[_Scenario, ...]:
    return _universe(settings.INVENTORY_MOCK_SKU_COUNT)


def _find(sku: str, sloc: str) -> _Scenario | None:
    return next((s for s in _scenarios() if s.sku == sku and s.sloc == sloc), None)


def _gap_on(scenario: _Scenario, day: date) -> int:
    return sum(e.impact for e in scenario.events if e.day <= day)


def _us(day: date) -> str:
    return day.strftime("%m/%d/%Y")


def _ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"code": 1, "msg": None, "data": data})


def _report_day(params: httpx.QueryParams) -> date:
    return date.today() - timedelta(days=int(params.get("date", "0")))


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


def _scr_report_summary(params: httpx.QueryParams) -> httpx.Response:
    day = _report_day(params)
    rows = []
    for sloc in MOCK_SLOCS:
        gaps = [_gap_on(s, day) for s in _scenarios() if s.sloc == sloc]
        rows.append(
            {
                "sloc": sloc,
                "absoluteGap": str(sum(abs(g) for g in gaps)),
                "netGap": str(sum(gaps)),
                "skuWithErrorNumber": str(sum(1 for g in gaps if g)),
            }
        )
    return _ok(rows)


def _scr_report_gap(params: httpx.QueryParams) -> httpx.Response:
    day, sloc = _report_day(params), params.get("sloc", "")
    rows = []
    for s in _scenarios():
        gap = _gap_on(s, day)
        if s.sloc != sloc or gap == 0:
            continue
        price = 10 + int(s.sku) % 90
        rows.append(
            {
                "material": s.sku,
                "description": f"Mock product {s.sku}",
                "synapseTotal": "100",
                "nerpTotal": str(100 + gap),
                "totalGap": str(abs(gap)),
                "absMapValue": f"{abs(gap) * price:.2f}",
                "netGap": str(gap),
                "netGapMapValue": f"{gap * price:.2f}",
                "sloc": sloc,
            }
        )
    rows.sort(key=lambda r: -int(r["totalGap"]))
    return _ok(rows)


def _dod_research(params: httpx.QueryParams) -> httpx.Response:
    scenario = _find(params.get("material", ""), params.get("sloc", ""))
    if scenario is None:
        return _ok([])
    today = date.today()
    rows = [
        {"material": scenario.sku, "date": _us(day), "gap": str(abs(_gap_on(scenario, day)))}
        for day in (today - timedelta(days=n) for n in range(_HISTORY_DAYS))
    ]
    return _ok(rows)  # newest first, like the real query


def _in_window(day: date, body: dict[str, Any]) -> bool:
    start = datetime.strptime(body["start"], "%Y-%m-%d").date()
    end = datetime.strptime(body["end"], "%Y-%m-%d").date()
    return start <= day <= end


def _events(body: dict[str, Any], kind: str) -> tuple[_Scenario | None, list[_Event]]:
    scenario = _find(str(body.get("sku", "")), str(body.get("sloc", "")))
    if scenario is None:
        return None, []
    return scenario, [e for e in scenario.events if e.kind == kind and _in_window(e.day, body)]


def _nerp_row(s: _Scenario, reference: str, qty: int, day: date, mvt: str) -> dict[str, Any]:
    return {
        "material": s.sku,
        "plnt": "C510",
        "sloc": s.sloc,
        "mvt": mvt,
        "movementTypeText": "GR goods receipt" if mvt == "101" else "Inventory adjustment",
        "specialStock": None,
        "reference": reference,
        "matDoc": f"49{int(hashlib.md5(reference.encode()).hexdigest()[:8], 16) % 10**8:08d}",
        "qty": f"{qty}.000",
        "userName": "BATCHUSER",
        "docHeader": "",
        "valType": "NEW",
        "postDate": _us(day),
        "postTime": "10:15:00",
        "entryDate": day.isoformat(),
    }


def _synapse_row(s: _Scenario, reference: str, qty: int, day: date, txn_type: str) -> dict[str, Any]:
    return {
        "item": s.sku,
        "reference": reference,
        "slot": s.sloc,
        "orderId": f"ORD{int(hashlib.md5(reference.encode()).hexdigest()[:8], 16) % 10**6:06d}",
        "originShipName": "",
        "lot": "",
        "po": "",
        "inventoryStatus": "AVAILABLE",
        "qty": str(qty),
        "transactionType": txn_type,
        "transactionDate": _us(day),
    }


def _sku_comparison(body: dict[str, Any]) -> httpx.Response:
    scenario, events = _events(body, "qty_mismatch")
    if scenario is None:
        return _ok([])
    return _ok(
        [
            {
                "reference": e.reference,
                "item": scenario.sku,
                "transactionType": "RECEIPT",
                "transactionDate": _us(e.day),
                "po": "",
                "inventoryStatus": "AVAILABLE",
                "mvt": "101",
                "postDate": _us(e.day),
                "postTime": "10:15:00",
                "entryDate": e.day.isoformat(),
                "synapseQty": "10",
                "nerpQty": str(10 + e.impact),
                "valType": "NEW",
            }
            for e in events
        ]
    )


def _missing_in_synapse(body: dict[str, Any]) -> httpx.Response:
    scenario, events = _events(body, "missing_in_synapse")
    if scenario is None:
        return _ok([])
    return _ok([_nerp_row(scenario, e.reference, e.impact, e.day, "101") for e in events])


def _missing_in_nerp(body: dict[str, Any]) -> httpx.Response:
    scenario, events = _events(body, "missing_in_nerp")
    if scenario is None:
        return _ok([])
    return _ok([_synapse_row(scenario, e.reference, -e.impact, e.day, "RECEIPT") for e in events])


def _noise_day(scenario: _Scenario, body: dict[str, Any]) -> date | None:
    if scenario.noise_adjustment_days_ago is None:
        return None
    day = date.today() - timedelta(days=scenario.noise_adjustment_days_ago)
    return day if _in_window(day, body) else None


def _nerp_adjustments(body: dict[str, Any]) -> httpx.Response:
    scenario, events = _events(body, "nerp_adjustment")
    if scenario is None:
        return _ok([])
    rows = [_nerp_row(scenario, "", e.impact, e.day, "701" if e.impact > 0 else "702") for e in events]
    noise = _noise_day(scenario, body)
    if noise:
        rows.append(_nerp_row(scenario, "", -3, noise, "702"))
    return _ok(rows)


def _synapse_adjustments(body: dict[str, Any]) -> httpx.Response:
    scenario, events = _events(body, "synapse_adjustment")
    if scenario is None:
        return _ok([])
    rows = [_synapse_row(scenario, "", -e.impact, e.day, "ADJUSTMENT") for e in events]
    noise = _noise_day(scenario, body)
    if noise:
        rows.append(_synapse_row(scenario, "", -3, noise, "ADJUSTMENT"))
    return _ok(rows)


_GET_ROUTES = {
    "/admin/scr/scrReportSummary": _scr_report_summary,
    "/admin/scr/scrReportGap": _scr_report_gap,
    "/admin/scr/dodResearch": _dod_research,
}
_POST_ROUTES = {
    "/admin/scr/skuComparision": _sku_comparison,
    "/admin/scr/skuComparisionMissingNerp": _missing_in_synapse,
    "/admin/scr/skuComparisionMissingItemActivity": _missing_in_nerp,
    "/admin/scr/skuDetailNERPAdj": _nerp_adjustments,
    "/admin/scr/skuDetailSynapseAdj": _synapse_adjustments,
}


def _handle(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.method == "GET" and path in _GET_ROUTES:
        return _GET_ROUTES[path](request.url.params)
    if request.method == "POST" and path in _POST_ROUTES:
        return _POST_ROUTES[path](json.loads(request.content or b"{}"))
    return httpx.Response(404, json={"code": 0, "msg": f"no mock route for {request.method} {path}", "data": None})


def build_mock_transport() -> httpx.MockTransport:
    """Return an httpx transport that serves the fake SCR API."""
    return httpx.MockTransport(_handle)
