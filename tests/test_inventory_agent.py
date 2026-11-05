"""End-to-end runs of the inventory gap graph against the mock SCR API (LLM, RAG and cache stubbed)."""

import asyncio
import json
from datetime import date
from typing import Any

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)

from app.core.cache import InMemoryCacheService
from app.core.config import settings
from app.core.langgraph import inventory_graph
from app.core.langgraph.inventory_graph import (
    InventoryGapAgent,
    is_simple,
)
from app.schemas.inventory import (
    LlmClassification,
    ResolutionDraft,
)
from app.schemas.rag import SearchResult
from app.services.inventory_client import InventoryClient
from app.services.inventory_mock import build_mock_transport

KB_TITLE = "SCR Reconciliation SOP"


class _StubLLM:
    """Classifies, runs one KB search per resolver, then returns a draft; the summary call fails."""

    def __init__(self, fail_resolution: bool = False) -> None:
        self.fail_resolution = fail_resolution
        self.calls: dict[str, int] = {"classify": 0, "resolver_turn": 0, "resolution": 0, "summary": 0}

    async def call(self, messages: Any, response_format: Any = None, tools: Any = None, **_: Any) -> Any:
        if response_format is LlmClassification:
            self.calls["classify"] += 1
            return LlmClassification(root_cause="timing_difference", hypothesis="stub", confidence="low")
        if response_format is ResolutionDraft:
            self.calls["resolution"] += 1
            if self.fail_resolution:
                raise RuntimeError("llm unavailable")
            return ResolutionDraft(
                rationale="stub",
                actions=["stub action"],
                procedure=["stub procedure"],
                kb_sources=[KB_TITLE, "Invented Document"],
                confidence="medium",
                needs_human_review=False,
            )
        if tools:  # resolver agent turn
            self.calls["resolver_turn"] += 1
            if any(isinstance(m, AIMessage) and m.tool_calls for m in messages):
                return AIMessage(content="done searching")
            finding = json.loads(str(next(m for m in messages if isinstance(m, HumanMessage)).content))
            query = f"{finding['root_cause']} procedure"
            return AIMessage(
                content="",
                tool_calls=[{"name": "rag_search", "args": {"query": query}, "id": "call-1", "type": "tool_call"}],
            )
        self.calls["summary"] += 1
        raise RuntimeError("summary unavailable")  # exercises the deterministic fallback report


class _StubRag:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, user_id: int, query: str) -> list[SearchResult]:
        self.queries.append(query)
        return [SearchResult(document_id="1", title=KB_TITLE, chunk_index=0, content="Do the thing.", distance=0.1)]

    async def format_results(self, results: list[SearchResult]) -> str:
        return "\n".join(f"[{r.title}] {r.content}" for r in results)


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> tuple[_StubLLM, _StubRag]:
    """Stub the LLM, the knowledge base and the cache."""
    llm, rag = _StubLLM(), _StubRag()
    monkeypatch.setattr(inventory_graph, "llm_service", llm)
    monkeypatch.setattr(inventory_graph, "rag_service", rag)
    monkeypatch.setattr(inventory_graph, "cache_service", InMemoryCacheService(default_ttl=60))
    monkeypatch.setattr(settings, "LANGFUSE_TRACING_ENABLED", False)
    return llm, rag


def _agent() -> InventoryGapAgent:
    return InventoryGapAgent(client=InventoryClient(transport=build_mock_transport()))


def test_full_investigation_against_mock(stubs: tuple[_StubLLM, _StubRag]):
    """Full investigation: deterministic findings, triage, resolver agents and roll-up."""
    llm, rag = stubs

    state = asyncio.run(_agent().run("test-run", date.today(), locations=None, user_id=1))

    assert state.total_gaps > 50
    assert len(state.findings) == state.total_gaps
    assert not [f for f in state.findings if f.error]

    rule_based = [f for f in state.findings if f.discrepancies]
    assert rule_based and all(f.explained for f in rule_based), "mock data should fully reconcile"
    assert all(f.origin_date is not None for f in state.findings)

    unexplained = [f for f in state.findings if not f.discrepancies]
    assert llm.calls["classify"] == len(unexplained)

    # every finding is resolved; simple ones by template, the rest by one agent each
    assert all(f.resolution is not None for f in state.findings)
    simple = [f for f in state.findings if is_simple(f)]
    complex_ = [f for f in state.findings if not is_simple(f)]
    assert simple and complex_
    assert all(f.resolution and f.resolution.method == "template" for f in simple)
    assert all(f.resolution and f.resolution.method == "agent" for f in complex_)
    assert llm.calls["resolution"] == len(complex_)
    assert llm.calls["resolver_turn"] == 2 * len(complex_)

    # citations are limited to documents actually retrieved; identical queries hit the cache
    assert all(f.resolution and f.resolution.kb_sources == [KB_TITLE] for f in complex_)
    assert len(rag.queries) == len(set(rag.queries)) < len(complex_)

    causes = {f.root_cause for f in state.findings}
    assert {p.root_cause for p in state.remediations} == causes
    assert all(p.steps for p in state.remediations)
    assert "Root cause" in state.report and "Highest-impact SKUs" in state.report


def test_resolver_failure_falls_back_to_template(stubs: tuple[_StubLLM, _StubRag]):
    """A failing resolver yields a fallback resolution flagged for review; the run still completes."""
    llm, _ = stubs
    llm.fail_resolution = True

    state = asyncio.run(_agent().run("test-run", date.today(), locations=["WR2E"], user_id=1))

    complex_ = [f for f in state.findings if not is_simple(f)]
    assert complex_
    assert all(f.resolution and f.resolution.method == "fallback" for f in complex_)
    assert all(f.resolution and f.resolution.needs_human_review and f.resolution.actions for f in complex_)


def test_template_threshold_zero_sends_every_sku_to_the_agent(
    stubs: tuple[_StubLLM, _StubRag], monkeypatch: pytest.MonkeyPatch
):
    """INVENTORY_TEMPLATE_MAX_DISCREPANCIES=0 disables templates."""
    llm, _ = stubs
    monkeypatch.setattr(settings, "INVENTORY_TEMPLATE_MAX_DISCREPANCIES", 0)

    state = asyncio.run(_agent().run("test-run", date.today(), locations=["WR2E"], user_id=1))

    assert all(f.resolution and f.resolution.method == "agent" for f in state.findings)
    assert llm.calls["resolution"] == len(state.findings)


def test_locations_filter_ignores_unknown_sloc(stubs: tuple[_StubLLM, _StubRag]):
    """Locations filter ignores unknown sloc."""
    state = asyncio.run(_agent().run("test-run", date.today(), locations=["WR2E", "NOPE"], user_id=None))

    assert {f.sloc for f in state.findings} == {"WR2E"}
