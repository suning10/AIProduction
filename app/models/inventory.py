"""Persistence models for inventory gap investigations."""

from datetime import (
    date,
    datetime,
)
from typing import (
    Any,
    Optional,
)

from sqlalchemy import (
    Column,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import BaseModel


class InventoryInvestigation(BaseModel, table=True):
    """One run of the inventory gap agent for a report date.

    Attributes:
        id: UUID string primary key
        user_id: Requesting user (scopes knowledge-base access and visibility)
        as_of_date: Gap report date investigated
        locations: Storage locations requested (``None`` = all with gaps)
        status: pending | running | completed | failed
        total_gaps: SKU/locations with a gap on the report date
        truncated: Whether the run was capped at INVENTORY_MAX_SKUS
        report: Final Markdown report
        remediations: Remediation plans (list of RemediationPlan dicts)
        error: Failure message when status is "failed"
        completed_at: When the run finished
    """

    __tablename__ = "inventory_investigation"  # pyright: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    as_of_date: date = Field(index=True)
    locations: Optional[list[str]] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    status: str = Field(default="pending")
    total_gaps: int = Field(default=0)
    truncated: bool = Field(default=False)
    report: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    remediations: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    completed_at: Optional[datetime] = Field(default=None)


class InventorySkuFinding(BaseModel, table=True):
    """Per-SKU/sloc result of an investigation; the full finding is kept in ``payload``."""

    __tablename__ = "inventory_sku_finding"  # pyright: ignore[reportAssignmentType]

    id: Optional[int] = Field(default=None, primary_key=True)
    investigation_id: str = Field(foreign_key="inventory_investigation.id", index=True)
    sku: str = Field(index=True)
    sloc: str
    gap: int
    root_cause: str = Field(index=True)
    explained: bool
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
