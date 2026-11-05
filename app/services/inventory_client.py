"""Config-driven client for the upstream SCR (inventory gap) APIs.

Every endpoint's URL, method, params/body templates, response record path and
field mapping come from ``settings.INVENTORY_ENDPOINTS_FILE`` (see
``app/core/inventory_endpoints.json``), so pointing the agent at a different
API — or adapting to a contract change — is a config edit, not a code change.

In ``INVENTORY_API_MODE=mock`` the same request/mapping path runs against an
in-process fake (``app/services/inventory_mock.py``) via ``httpx.MockTransport``.
"""

import asyncio
import json
import os
from datetime import date
from typing import (
    Any,
    Optional,
    TypeVar,
)
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    ValidationError,
)
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.cache import (
    cache_key,
    cache_service,
)
from app.core.config import settings
from app.core.logging import logger
from app.schemas.inventory import (
    DayOverDayPoint,
    EndpointConfig,
    EndpointName,
    GapRecord,
    InventoryApiConfig,
    QtyMismatchRecord,
    ReconciliationData,
    SlocSummary,
    TxnRecord,
)
from app.services.inventory_mock import build_mock_transport

T = TypeVar("T", bound=BaseModel)

MOCK_BASE_URL = "http://scr-mock.local"
_QTY_FIELDS = ("qty", "nerp_qty", "synapse_qty")
_UNQUOTED_VARS = {"base_url"}  # already a URL; every other variable is escaped when placed in a URL path


class InventoryApiError(Exception):
    """An upstream SCR API call failed or returned an unusable response."""


class _SafeFormat(dict):
    """format_map dict that leaves unknown ``{placeholders}`` untouched."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render(template: Any, variables: dict[str, str], quote_values: bool = False) -> Any:
    """Fill ``{var}`` placeholders and ``${ENV}`` references in a (nested) template."""
    if isinstance(template, str):
        values = (
            {k: v if k in _UNQUOTED_VARS else quote(v, safe="") for k, v in variables.items()}
            if quote_values
            else variables
        )
        return os.path.expandvars(template.format_map(_SafeFormat(values)))
    if isinstance(template, dict):
        return {k: _render(v, variables, quote_values) for k, v in template.items()}
    if isinstance(template, list):
        return [_render(v, variables, quote_values) for v in template]
    return template


def _get_path(payload: Any, path: str) -> Any:
    """Read a dot-separated path ("data.items") from parsed JSON; "" returns the payload."""
    current = payload
    for part in filter(None, path.split(".")):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_retryable(error: BaseException) -> bool:
    """Retry transport failures, 5xx and 429 — never other 4xx or contract errors."""
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500 or error.response.status_code == 429
    return False


def load_api_config() -> InventoryApiConfig:
    """Load and validate the endpoint contract file."""
    with open(settings.INVENTORY_ENDPOINTS_FILE, "r") as f:
        raw = json.load(f)
    return InventoryApiConfig.model_validate(raw)


class InventoryClient:
    """Async client for the SCR APIs with retries, success-only caching and a concurrency cap."""

    def __init__(
        self, config: Optional[InventoryApiConfig] = None, transport: Optional[httpx.AsyncBaseTransport] = None
    ):
        """Create the client.

        Args:
            config: Endpoint contracts; loaded from ``INVENTORY_ENDPOINTS_FILE`` when omitted.
            transport: Optional httpx transport override (tests). Mock mode supplies its own.
        """
        self._config = config
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(settings.INVENTORY_MAX_CONCURRENCY)
        self._mock = settings.INVENTORY_API_MODE == "mock" and transport is None
        self._base_url = MOCK_BASE_URL if self._mock else settings.INVENTORY_API_BASE_URL

    @property
    def config(self) -> InventoryApiConfig:
        """Endpoint contracts, loaded on first use."""
        if self._config is None:
            self._config = load_api_config()
            logger.info(
                "inventory_api_config_loaded",
                path=str(settings.INVENTORY_ENDPOINTS_FILE),
                mode=settings.INVENTORY_API_MODE,
                endpoints=list(self._config.endpoints),
            )
        return self._config

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            transport = self._transport or (build_mock_transport() if self._mock else None)
            self._client = httpx.AsyncClient(timeout=settings.INVENTORY_API_TIMEOUT_SECONDS, transport=transport)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Generic request path
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _send(self, endpoint: EndpointConfig, variables: dict[str, str]) -> Any:
        """Send one request and return the parsed JSON body."""
        url = _render(endpoint.url, variables, quote_values=True)
        params = _render(endpoint.params, variables) or None
        headers = _render(endpoint.headers, variables) or None
        body = _render(endpoint.body, variables) if endpoint.body is not None else None

        async with self._semaphore:
            response = await self._get_client().request(
                endpoint.method, url, params=params, json=body, headers=headers
            )
        response.raise_for_status()
        return response.json()

    def _check_envelope(self, name: str, payload: Any) -> None:
        envelope = self.config.envelope
        if envelope is None or not isinstance(payload, dict):
            return
        code = _get_path(payload, envelope.code_path)
        if code not in envelope.success_values:
            message = _get_path(payload, envelope.message_path)
            raise InventoryApiError(f"{name} returned code={code!r}: {message}")

    def _map_records(self, endpoint: EndpointConfig, records: list[Any]) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            row = dict(record) if not endpoint.field_map else {}
            for canonical, source in endpoint.field_map.items():
                row[canonical] = _get_path(record, source)
            if endpoint.qty_multiplier != 1:
                for qty_field in _QTY_FIELDS:
                    if row.get(qty_field) not in (None, ""):
                        row[qty_field] = float(str(row[qty_field]).replace(",", "")) * endpoint.qty_multiplier
            mapped.append(row)
        return mapped

    async def fetch(self, name: EndpointName, model: type[T], **variables: str) -> list[T]:
        """Call a configured endpoint and return its records as ``model`` instances.

        Successful responses are cached for ``INVENTORY_API_CACHE_TTL_SECONDS``;
        errors and contract violations are never cached.

        Raises:
            InventoryApiError: On HTTP failure after retries, a non-success
                envelope code, or records that don't fit ``model``.
        """
        endpoint = self.config.endpoints.get(name)
        if endpoint is None:
            raise InventoryApiError(f"endpoint '{name}' is not configured in {settings.INVENTORY_ENDPOINTS_FILE}")

        all_vars = {"base_url": self._base_url, **variables}
        key = cache_key("inventory_api", name, json.dumps(all_vars, sort_keys=True))
        cached = await cache_service.get(key)
        if cached is not None:
            return [model.model_validate(row) for row in json.loads(cached)]

        try:
            payload = await self._send(endpoint, all_vars)
        except httpx.HTTPError as e:
            logger.exception("inventory_api_request_failed", endpoint=name, **variables)
            raise InventoryApiError(f"{name} request failed: {e}") from e

        self._check_envelope(name, payload)
        records = _get_path(payload, endpoint.records_path)
        if records is None:
            records = []
        if not isinstance(records, list):
            raise InventoryApiError(
                f"{name}: expected a list at '{endpoint.records_path}', got {type(records).__name__}"
            )

        rows = self._map_records(endpoint, records)
        try:
            parsed = [model.model_validate(row) for row in rows]
        except ValidationError as e:
            raise InventoryApiError(f"{name}: response does not match the configured field_map: {e}") from e

        await cache_service.set(
            key,
            json.dumps([p.model_dump(mode="json") for p in parsed]),
            ttl=settings.INVENTORY_API_CACHE_TTL_SECONDS,
        )
        logger.debug("inventory_api_fetched", endpoint=name, record_count=len(parsed))
        return parsed

    # ------------------------------------------------------------------
    # Typed helpers
    # ------------------------------------------------------------------

    @staticmethod
    def days_ago(as_of: date) -> str:
        """The SCR report endpoints address dates as an offset from today."""
        return str((date.today() - as_of).days)

    async def get_sloc_summary(self, as_of: date) -> list[SlocSummary]:
        """Per-storage-location gap summary for a report date."""
        return await self.fetch("sloc_summary", SlocSummary, days_ago=self.days_ago(as_of), date=as_of.isoformat())

    async def get_gaps(self, as_of: date, sloc: str) -> list[GapRecord]:
        """SKUs with a gap at one storage location on a report date."""
        records = await self.fetch("gaps", GapRecord, days_ago=self.days_ago(as_of), date=as_of.isoformat(), sloc=sloc)
        for record in records:
            record.sloc = record.sloc or sloc
        return records

    async def get_day_over_day(self, sku: str, sloc: str) -> list[DayOverDayPoint]:
        """Daily gap history for one SKU/sloc."""
        return await self.fetch("day_over_day", DayOverDayPoint, sku=sku, sloc=sloc)

    async def get_reconciliation_data(self, sku: str, sloc: str, start: date, end: date) -> ReconciliationData:
        """Fetch all transaction-level discrepancy sources for one SKU/sloc and window concurrently."""
        window = {"sku": sku, "sloc": sloc, "start": start.isoformat(), "end": end.isoformat()}
        mismatches, missing_syn, missing_nerp, nerp_adj, syn_adj = await asyncio.gather(
            self.fetch("qty_mismatch", QtyMismatchRecord, **window),
            self.fetch("missing_in_synapse", TxnRecord, **window),
            self.fetch("missing_in_nerp", TxnRecord, **window),
            self.fetch("nerp_adjustments", TxnRecord, **window),
            self.fetch("synapse_adjustments", TxnRecord, **window),
        )
        return ReconciliationData(
            qty_mismatches=mismatches,
            missing_in_synapse=missing_syn,
            missing_in_nerp=missing_nerp,
            nerp_adjustments=nerp_adj,
            synapse_adjustments=syn_adj,
        )


inventory_client = InventoryClient()
