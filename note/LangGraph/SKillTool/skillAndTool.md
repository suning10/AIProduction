# Tools vs. Skills + Tools in LangGraph

- Tool
  - for workflow like single agent 
  - Issues with Tool only Design
    - LLM see all tools and get confused 
    - best for < 5 tools 
    - one prompt vs different prompt per skill 
- Skills
  - Agent gets confused choosing between many tools
  - You need specialized behavior per domain
  - Tasks require parallel processing
  - You're building multi-agent systems

## Understanding the Concepts

```
┌─────────────────────────────────────────────────────┐
│                    TOOLS                             │
│  - Atomic, single-purpose functions                 │
│  - search_web(), query_db(), send_email()           │
│  - Low-level capabilities                           │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                    SKILLS                            │
│  - Higher-level composed capabilities               │
│  - Combine multiple tools + logic                   │
│  - Sub-graphs or specialized agent nodes            │
└─────────────────────────────────────────────────────┘
```

---

## When Tools Alone Are Sufficient

```python
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

@tool
def search_web(query: str) -> str:
    """Search the web for information"""
    return "search results..."

@tool
def calculate(expression: str) -> str:
    """Perform calculations"""
    return eval(expression)

# Simple - just tools + agent
agent = create_react_agent(
    model=llm,
    tools=[search_web, calculate]
)
```

✅ **Use tools only when:**
- Simple, linear workflows
- Single agent can handle everything
- Tasks are straightforward (< 3-4 tool calls)
- No domain specialization needed

---

## When Skills + Tools Together Are Better

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    current_skill: str

# ── Tools (atomic) ──────────────────────────────────
@tool
def fetch_stock_price(ticker: str) -> str:
    """Get current stock price"""
    return f"${ticker}: $150.00"

@tool
def fetch_news(company: str) -> str:
    """Get latest news"""
    return f"News about {company}..."

@tool
def calculate_metrics(data: str) -> str:
    """Calculate financial metrics"""
    return "P/E ratio: 25"

@tool
def send_report(content: str) -> str:
    """Send report via email"""
    return "Report sent!"

# ── Skills (composed capabilities) ──────────────────
def financial_analysis_skill(state: AgentState):
    """SKILL: Combines multiple financial tools"""
    agent = create_react_agent(
        llm,
        tools=[fetch_stock_price, calculate_metrics, fetch_news]
    )
    result = agent.invoke(state)
    return {"messages": result["messages"], "current_skill": "financial"}

def reporting_skill(state: AgentState):
    """SKILL: Handles report generation + delivery"""
    agent = create_react_agent(
        llm,
        tools=[send_report]
    )
    result = agent.invoke(state)
    return {"messages": result["messages"], "current_skill": "reporting"}

def router(state: AgentState):
    """Route to appropriate skill"""
    last_message = state["messages"][-1].content
    if "analyze" in last_message.lower():
        return "financial_analysis"
    return "reporting"

# ── Graph (orchestrating skills) ────────────────────
graph = StateGraph(AgentState)

graph.add_node("financial_analysis", financial_analysis_skill)
graph.add_node("reporting", reporting_skill)

graph.add_conditional_edges(START, router, {
    "financial_analysis": "financial_analysis",
    "reporting": "reporting"
})
graph.add_edge("financial_analysis", "reporting")
graph.add_edge("reporting", END)

app = graph.compile()
```

---

## Architecture Comparison

```
TOOLS ONLY:
┌──────────┐    ┌──────────────────────────────┐
│  Agent   │───▶│  tool1, tool2, tool3, tool4  │
└──────────┘    └──────────────────────────────┘
  Simple but agent can get overwhelmed with many tools

SKILLS + TOOLS:
┌──────────────┐
│  Supervisor  │
└──────┬───────┘
       │
  ┌────┴─────┐
  │  Router  │
  └────┬─────┘
       │
┌──────┴──────────────────┐
│                         │
▼                         ▼
┌─────────────┐    ┌─────────────┐
│   SKILL A   │    │   SKILL B   │
│  (Agent)    │    │  (Agent)    │
├─────────────┤    ├─────────────┤
│ tool1       │    │ tool3       │
│ tool2       │    │ tool4       │
└─────────────┘    └─────────────┘
  Focused, specialized, scalable
```

---

## Decision Guide

| Scenario | Recommendation |
|----------|---------------|
| < 5 tools, simple task | **Tools only** |
| > 5 tools | **Skills + Tools** |
| Multi-domain tasks | **Skills + Tools** |
| Multiple agents needed | **Skills + Tools** |
| Need tool isolation | **Skills + Tools** |
| RAG + Action pipeline | **Skills + Tools** |
| Quick prototype | **Tools only** |

---

## Key Benefits of Skills + Tools

```python
# Skills provide:

# 1. TOOL ISOLATION - each skill only sees relevant tools
research_skill_tools = [search, scrape, summarize]      # 3 tools
coding_skill_tools   = [write_code, run_code, debug]    # 3 tools
# vs. agent seeing all 6 → less confusion

# 2. REUSABILITY - plug skills into different graphs
graph1.add_node("research", research_skill)
graph2.add_node("research", research_skill)  # reused!

# 3. PARALLELISM - run skills concurrently
graph.add_edge("skill_a", "merge_node")
graph.add_edge("skill_b", "merge_node")  # parallel execution

# 4. TESTABILITY - test skills independently
result = research_skill.invoke({"messages": [test_message]})
```

---

## Recommendation

> **Start with tools only**, then refactor to skills + tools when you notice:
> - Agent gets confused choosing between many tools
> - You need specialized behavior per domain  
> - Tasks require parallel processing
> - You're building multi-agent systems