"""Persistence and background execution for inventory gap investigations."""

import asyncio
import uuid
from collections import Counter
from datetime import (
    UTC,
    date,
    datetime,
)
from typing import Optional

from sqlmodel import (
    Session,
    col,
    select,
)

from app.core.langgraph.inventory_graph import inventory_gap_agent
from app.core.logging import logger
from app.models.inventory import (
    InventoryInvestigation,
    InventorySkuFinding,
)
from app.schemas.inventory import (
    InvestigationDetail,
    InvestigationSummary,
    RemediationPlan,
    SkuFinding,
)
from app.services.database import database_service

# Strong references so background runs aren't garbage-collected mid-flight
_running_tasks: set[asyncio.Task] = set()


def _to_summary(row: InventoryInvestigation) -> InvestigationSummary:
    return InvestigationSummary(
        id=row.id,
        as_of_date=row.as_of_date,
        locations=row.locations,
        status=row.status,  # type: ignore[arg-type]
        total_gaps=row.total_gaps,
        truncated=row.truncated,
        report=row.report,
        error=row.error,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


class InventoryInvestigationService:
    """Creates, runs and reads inventory gap investigations."""

    def __init__(self):
        """Reuse the shared database engine."""
        self.engine = database_service.engine

    async def create(self, user_id: int, as_of: date, locations: Optional[list[str]]) -> InvestigationSummary:
        """Persist a pending investigation and start it in the background."""
        row = InventoryInvestigation(
            id=str(uuid.uuid4()), user_id=user_id, as_of_date=as_of, locations=locations, status="pending"
        )
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
            session.refresh(row)
        summary = _to_summary(row)

        task = asyncio.create_task(self._run(row.id, as_of, locations, user_id))
        _running_tasks.add(task)
        task.add_done_callback(_running_tasks.discard)
        logger.info("inventory_investigation_created", investigation_id=row.id, user_id=user_id, as_of=str(as_of))
        return summary

    async def _run(self, investigation_id: str, as_of: date, locations: Optional[list[str]], user_id: int) -> None:
        """Execute the graph and store its results; failures mark the investigation failed."""
        self._update(investigation_id, status="running")
        try:
            state = await inventory_gap_agent.run(investigation_id, as_of, locations, user_id)
        except Exception as e:
            logger.exception("inventory_investigation_failed", investigation_id=investigation_id)
            self._update(investigation_id, status="failed", error=str(e), completed_at=datetime.now(UTC))
            return

        with Session(self.engine) as session:
            row = session.get(InventoryInvestigation, investigation_id)
            if row is None:
                logger.warning("inventory_investigation_missing_on_complete", investigation_id=investigation_id)
                return
            row.status = "completed"
            row.total_gaps = state.total_gaps
            row.truncated = state.truncated
            row.report = state.report
            row.remediations = [p.model_dump(mode="json") for p in state.remediations]
            row.completed_at = datetime.now(UTC)
            session.add(row)
            session.add_all(
                InventorySkuFinding(
                    investigation_id=investigation_id,
                    sku=f.sku,
                    sloc=f.sloc,
                    gap=f.gap,
                    root_cause=f.root_cause,
                    explained=f.explained,
                    payload=f.model_dump(mode="json"),
                )
                for f in state.findings
            )
            session.commit()
        logger.info(
            "inventory_investigation_completed",
            investigation_id=investigation_id,
            finding_count=len(state.findings),
            remediation_count=len(state.remediations),
        )

    def _update(self, investigation_id: str, **fields: object) -> None:
        with Session(self.engine) as session:
            row = session.get(InventoryInvestigation, investigation_id)
            if row is None:
                return
            for name, value in fields.items():
                setattr(row, name, value)
            session.add(row)
            session.commit()

    def _get_owned(self, session: Session, investigation_id: str, user_id: int) -> Optional[InventoryInvestigation]:
        row = session.get(InventoryInvestigation, investigation_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[InvestigationSummary]:
        """Most recent investigations started by the user."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(InventoryInvestigation)
                .where(InventoryInvestigation.user_id == user_id)
                .order_by(col(InventoryInvestigation.created_at).desc())
                .limit(limit)
            ).all()
            return [_to_summary(r) for r in rows]

    async def get_detail(
        self, investigation_id: str, user_id: int, root_cause: Optional[str] = None
    ) -> Optional[InvestigationDetail]:
        """Investigation with remediation plans and findings; ``None`` if missing or not the user's."""
        with Session(self.engine) as session:
            row = self._get_owned(session, investigation_id, user_id)
            if row is None:
                return None
            findings = session.exec(
                select(InventorySkuFinding).where(InventorySkuFinding.investigation_id == investigation_id)
            ).all()
            counts = Counter(f.root_cause for f in findings)
            selected = [f for f in findings if root_cause is None or f.root_cause == root_cause]
            selected.sort(key=lambda f: abs(f.gap), reverse=True)
            return InvestigationDetail(
                **_to_summary(row).model_dump(),
                root_cause_counts=dict(counts),
                remediations=[RemediationPlan.model_validate(p) for p in row.remediations],
                findings=[SkuFinding.model_validate(f.payload) for f in selected],
            )

    async def get_sku_findings(self, investigation_id: str, user_id: int, sku: str) -> Optional[list[SkuFinding]]:
        """All locations' findings for one SKU; ``None`` if the investigation is missing or not the user's."""
        with Session(self.engine) as session:
            if self._get_owned(session, investigation_id, user_id) is None:
                return None
            rows = session.exec(
                select(InventorySkuFinding).where(
                    InventorySkuFinding.investigation_id == investigation_id, InventorySkuFinding.sku == sku
                )
            ).all()
            return [SkuFinding.model_validate(r.payload) for r in rows]


inventory_investigation_service = InventoryInvestigationService()
