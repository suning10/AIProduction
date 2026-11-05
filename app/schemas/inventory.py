"""Schemas for the inventory gap (SCR) investigation workflow.

Sign convention (matches the SCR report's ``netGap``): ``gap = NERP qty - Synapse qty``.
Transaction quantities are signed (positive = inbound). A discrepancy's
``impact`` is its contribution to the gap, so a fully explained SKU satisfies
``sum(d.impact for d in discrepancies) == gap``.
"""

import datetime as dt
import operator
from datetime import (
    date,
    datetime,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import (
    Annotated,
    Any,
    Literal,
    Optional,
)

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
)

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%m/%d/%y")


def _parse_int(value: Any) -> int:
    """Coerce upstream numeric strings ("5", "5.000", "", None) to int."""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(round(value))
    try:
        return int(Decimal(str(value).strip().replace(",", "")).to_integral_value())
    except InvalidOperation as e:
        raise ValueError(f"not a number: {value!r}") from e


def _parse_float(value: Any) -> float:
    """Coerce upstream numeric strings to float, treating blanks as 0."""
    if value is None or value == "":
        return 0.0
    return float(str(value).strip().replace(",", ""))


def _parse_date(value: Any) -> Optional[date]:
    """Parse the date formats the SCR APIs emit (ISO and MM/dd/yyyy)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


def _parse_str(value: Any) -> str:
    return "" if value is None else str(value)


Qty = Annotated[int, BeforeValidator(_parse_int)]
Amount = Annotated[float, BeforeValidator(_parse_float)]
UpstreamDate = Annotated[Optional[date], BeforeValidator(_parse_date)]
RequiredDate = Annotated[date, BeforeValidator(_parse_date)]
Text = Annotated[str, BeforeValidator(_parse_str)]

DiscrepancyKind = Literal[
    "missing_in_synapse",
    "missing_in_nerp",
    "qty_mismatch",
    "nerp_adjustment",
    "synapse_adjustment",
]
RootCause = Literal[
    "missing_in_synapse",
    "missing_in_nerp",
    "qty_mismatch",
    "nerp_adjustment",
    "synapse_adjustment",
    "timing_difference",
    "unexplained",
    "error",
]
InvestigationStatus = Literal["pending", "running", "completed", "failed"]
ResolutionMethod = Literal["agent", "template", "fallback"]
EndpointName = Literal[
    "sloc_summary",
    "gaps",
    "day_over_day",
    "qty_mismatch",
    "missing_in_synapse",
    "missing_in_nerp",
    "nerp_adjustments",
    "synapse_adjustments",
]


# ---------------------------------------------------------------------------
# Upstream API configuration (loaded from INVENTORY_ENDPOINTS_FILE)
# ---------------------------------------------------------------------------


class EndpointConfig(BaseModel):
    """How to call one upstream endpoint and map its records to canonical fields."""

    method: Literal["GET", "POST"] = "GET"
    url: str
    params: dict[str, str] = Field(default_factory=dict)
    body: Optional[dict[str, Any]] = None
    headers: dict[str, str] = Field(default_factory=dict)
    records_path: str = ""
    field_map: dict[str, str] = Field(default_factory=dict)
    qty_multiplier: int = 1


class EnvelopeConfig(BaseModel):
    """Response wrapper check, e.g. ``Result{code, msg, data}``."""

    code_path: str = "code"
    success_values: list[Any] = Field(default_factory=lambda: [1])
    message_path: str = "msg"


class InventoryApiConfig(BaseModel):
    """All upstream endpoint definitions."""

    envelope: Optional[EnvelopeConfig] = None
    endpoints: dict[EndpointName, EndpointConfig]


# ---------------------------------------------------------------------------
# Canonical upstream records
# ---------------------------------------------------------------------------


class SlocSummary(BaseModel):
    """One storage location's gap summary for a date."""

    sloc: Text
    skus_with_gap: Qty = 0
    net_gap: Qty = 0


class GapRecord(BaseModel):
    """One SKU/sloc row from the SCR gap report."""

    sku: Text
    sloc: Text
    description: Text = ""
    nerp_qty: Qty = 0
    synapse_qty: Qty = 0
    gap: Qty = Field(default=0, description="Net gap, NERP - Synapse")
    abs_gap: Qty = 0
    gap_value: Amount = 0.0


class DayOverDayPoint(BaseModel):
    """The (absolute) gap for one SKU/sloc on one date."""

    date: RequiredDate
    gap: Qty


class TxnRecord(BaseModel):
    """A one-sided transaction (missing on the other system, or an unreferenced adjustment)."""

    reference: Text = ""
    txn_type: Text = ""
    txn_date: UpstreamDate = None
    qty: Qty = 0
    doc: Text = ""
    user: Text = ""


class QtyMismatchRecord(BaseModel):
    """A reference present in both systems with different quantities."""

    reference: Text = ""
    txn_type: Text = ""
    txn_date: UpstreamDate = None
    nerp_qty: Qty = 0
    synapse_qty: Qty = 0


class ReconciliationData(BaseModel):
    """Everything fetched from the transaction endpoints for one SKU/sloc and date window."""

    qty_mismatches: list[QtyMismatchRecord] = Field(default_factory=list)
    missing_in_synapse: list[TxnRecord] = Field(default_factory=list)
    missing_in_nerp: list[TxnRecord] = Field(default_factory=list)
    nerp_adjustments: list[TxnRecord] = Field(default_factory=list)
    synapse_adjustments: list[TxnRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Analysis results
# ---------------------------------------------------------------------------


class GapChange(BaseModel):
    """A date on which the absolute gap changed, and by how much."""

    date: dt.date
    abs_gap: int
    delta: int


class GapHistory(BaseModel):
    """When the current gap started and how it evolved day over day."""

    origin_date: Optional[date] = None
    origin_truncated: bool = Field(
        default=False, description="Gap was already non-zero at the start of the lookback window"
    )
    changes: list[GapChange] = Field(default_factory=list)


class Discrepancy(BaseModel):
    """A transaction-level difference between NERP and Synapse."""

    kind: DiscrepancyKind
    reference: str = ""
    txn_type: str = ""
    txn_date: Optional[date] = None
    nerp_qty: Optional[int] = None
    synapse_qty: Optional[int] = None
    impact: int = Field(description="Contribution to the net gap (NERP - Synapse)")


class LlmClassification(BaseModel):
    """LLM fallback verdict for a SKU the rule engine could not explain."""

    root_cause: RootCause = Field(description="Most likely root cause category")
    hypothesis: str = Field(description="One or two sentences on the likely cause and what to check next")
    confidence: Literal["low", "medium", "high"]


class ResolutionDraft(BaseModel):
    """Structured output of the per-SKU resolver agent."""

    rationale: str = Field(description="One or two sentences: what caused this SKU's gap, based on the evidence")
    actions: list[str] = Field(
        description="Ordered, SKU-specific actions citing the actual references, quantities, dates and system"
    )
    procedure: list[str] = Field(
        default_factory=list,
        description="The general SOP steps for this kind of discrepancy (no SKU specifics), from the knowledge base",
    )
    kb_sources: list[str] = Field(
        default_factory=list, description="Titles of knowledge-base documents the steps were drawn from"
    )
    confidence: Literal["low", "medium", "high"]
    needs_human_review: bool = Field(description="True when the knowledge base did not cover this case well")


class SkuResolution(BaseModel):
    """How to resolve one SKU/sloc's gap."""

    sku: str
    sloc: str
    method: ResolutionMethod
    rationale: str = ""
    actions: list[str] = Field(default_factory=list)
    procedure: list[str] = Field(default_factory=list)
    kb_sources: list[str] = Field(default_factory=list)
    kb_queries: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    needs_human_review: bool = False


class SkuFinding(BaseModel):
    """Investigation result for one SKU at one storage location."""

    sku: str
    sloc: str
    description: str = ""
    gap: int
    abs_gap: int = 0
    gap_value: float = 0.0
    origin_date: Optional[date] = None
    origin_truncated: bool = False
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    changes: list[GapChange] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    explained_qty: int = 0
    root_cause: RootCause = "unexplained"
    explained: bool = False
    hypothesis: Optional[str] = None
    error: Optional[str] = None
    resolution: Optional[SkuResolution] = None


class RemediationPlan(BaseModel):
    """Roll-up of the per-SKU resolutions sharing one root cause.

    ``steps`` is the general procedure (from the highest-impact agent resolution
    in the group); the SKU-specific actions live on each finding's ``resolution``.
    """

    root_cause: RootCause
    sku_count: int
    total_net_gap: int
    total_abs_gap: int
    skus: list[str]
    steps: list[str]
    kb_sources: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    review_count: int = 0


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class InventoryGapState(BaseModel):
    """State for the inventory gap investigation graph."""

    investigation_id: str = ""
    as_of: Optional[date] = None
    locations: Optional[list[str]] = None
    total_gaps: int = 0
    truncated: bool = False
    findings: Annotated[list[SkuFinding], operator.add] = Field(default_factory=list)
    resolutions: Annotated[list[SkuResolution], operator.add] = Field(default_factory=list)
    remediations: list[RemediationPlan] = Field(default_factory=list)
    report: str = ""
    # Per-branch payloads delivered via Send
    current_gap: Optional[GapRecord] = None
    current_finding: Optional[SkuFinding] = None


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------


class InvestigationCreate(BaseModel):
    """Request to start an investigation."""

    date: dt.date = Field(description="Gap report date to investigate (today or earlier)")
    locations: Optional[list[str]] = Field(
        default=None, description="Storage locations (sloc) to include; all locations with gaps when omitted"
    )


class InvestigationSummary(BaseModel):
    """Investigation status and report."""

    id: str
    as_of_date: date
    locations: Optional[list[str]] = None
    status: InvestigationStatus
    total_gaps: int
    truncated: bool
    report: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class InvestigationDetail(InvestigationSummary):
    """Investigation with remediation plans and per-SKU findings."""

    root_cause_counts: dict[str, int] = Field(default_factory=dict)
    remediations: list[RemediationPlan] = Field(default_factory=list)
    findings: list[SkuFinding] = Field(default_factory=list)
