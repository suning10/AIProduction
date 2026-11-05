"""Inventory gap (SCR) investigation endpoints.

``POST /investigations`` starts a background run of the inventory gap agent
(100+ SKUs take far too long for one request) and returns 202 with the
investigation id; poll ``GET /investigations/{id}`` for status and results.
Visibility is restricted to the user who started the investigation.
"""

from datetime import date
from typing import (
    List,
    Optional,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import logger
from app.models.user import User
from app.schemas.inventory import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationSummary,
    RootCause,
    SkuFinding,
)
from app.services.inventory_investigation import inventory_investigation_service
from app.utils.sanitization import sanitize_string

router = APIRouter()


@router.post("/investigations", response_model=InvestigationSummary, status_code=202)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["inventory_investigate"][0])
async def create_investigation(
    request: Request,
    body: InvestigationCreate,
    user: User = Depends(get_current_user),
) -> InvestigationSummary:
    """Start investigating inventory gaps for a report date.

    Args:
        request: The FastAPI request object for rate limiting.
        body: Report date and optional storage locations.
        user: The authenticated user.

    Returns:
        InvestigationSummary: The pending investigation.

    Raises:
        HTTPException: 422 if the date is in the future.
    """
    if body.date > date.today():
        raise HTTPException(status_code=422, detail="date cannot be in the future")

    locations = [sanitize_string(loc).strip().upper() for loc in body.locations] if body.locations else None
    summary = await inventory_investigation_service.create(user.id, body.date, locations)
    logger.info("inventory_investigation_requested", investigation_id=summary.id, user_id=user.id)
    return summary


@router.get("/investigations", response_model=List[InvestigationSummary])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["inventory_read"][0])
async def list_investigations(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> List[InvestigationSummary]:
    """List the user's most recent investigations."""
    return await inventory_investigation_service.list_for_user(user.id, limit)


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["inventory_read"][0])
async def get_investigation(
    request: Request,
    investigation_id: str,
    root_cause: Optional[RootCause] = Query(default=None, description="Only return findings with this root cause"),
    user: User = Depends(get_current_user),
) -> InvestigationDetail:
    """Get an investigation's status, report, remediation plans and per-SKU findings.

    Raises:
        HTTPException: 404 if not found or not owned by the user.
    """
    detail = await inventory_investigation_service.get_detail(investigation_id, user.id, root_cause)
    if detail is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return detail


@router.get("/investigations/{investigation_id}/skus/{sku}", response_model=List[SkuFinding])
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["inventory_read"][0])
async def get_sku_findings(
    request: Request,
    investigation_id: str,
    sku: str,
    user: User = Depends(get_current_user),
) -> List[SkuFinding]:
    """Get one SKU's findings (all storage locations) from an investigation.

    Raises:
        HTTPException: 404 if the investigation is not found or not owned by the user.
    """
    findings = await inventory_investigation_service.get_sku_findings(investigation_id, user.id, sku)
    if findings is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return findings
