# Summary

## how to handle recursive call limits
- can't have tool call iteratively
- langgraph have a limit of 25 round

### Two Solutions
- add recursive_limits in config(RunnableConfig)
- add count, append user message

Claude's Plan

```text
- app/core/config.py — new MAX_TOOL_CALLS_PER_TURN setting (env-overridable, defaults to 5).
- app/schemas/graph.py — GraphState.tool_call_count tracks tool-call rounds within a turn.
  - app/core/langgraph/graph.py:
   - _tool_call increments tool_call_count each round.
    - _chat checks the count against the cap; once reached, it appends a user-role nudge ("summarize your findings, don't call more tools") and routes the LLM call through model_name=..., which bypasses bind_tools entirely — the
  model literally has no tool schema for that call, so it can't emit tool_calls, and goto is forced to END.
    - get_response/get_stream_response reset tool_call_count: 0 on fresh turns (not on interrupt-resume, so a human-in-the-loop pause doesn't lose its budget).
```

```text
  Then call the LLM. Two design choices to flag:

  - Prompt-only (your literal ask) — keep tools bound, add the nudge, hope the model complies, and still force goto=END regardless of what comes back.
    - Risk: if the model ignores the nudge and emits tool_calls anyway, we'd either have to execute one more round (defeating the cap) or discard an AIMessage that has tool_calls with no matching ToolMessage — that's an invalid
  message sequence and will break the next turn when the full history gets replayed to OpenAI (tool_calls must be followed by tool results).
  - Prompt + mechanical guarantee (what I'd recommend) — same nudge message, but also make this one call via llm_service.call(messages, model_name=model_name) instead of the default self.llm_service.call(messages). Passing model_name
  routes through LLMService's "override path" (service.py:267-286), which builds the model fresh from LLMRegistry without bind_tools ever being applied — so the model has no tool schema and structurally cannot return tool_calls. The
  nudge message then does its intended job (steering what it says), while the missing tool schema guarantees that it can't call a tool, avoiding the dangling-tool-call problem entirely. Always goto=END after this call.
```

# Limiting Recursive Calls in LangGraph ReAct

Here are the main approaches to control recursion/iteration limits:

---

## 1. Built-in `recursion_limit` (Simplest)

```python
from langgraph.graph import StateGraph, END

# Set at invocation time
result = graph.invoke(
    {"messages": [HumanMessage(content="your question")]},
    config={"recursion_limit": 10}  # default is 25
)

# Or set at compile time
app = graph.compile()
app.invoke(input, config={"recursion_limit": 10})
```

> ⚠️ This raises a `GraphRecursionError` when the limit is hit — not always graceful.

---

## 2. Iteration Counter in State (Recommended)

```python
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

# --- State with counter ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    iteration_count: int
    max_iterations: int

# --- Nodes ---
def agent_node(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {
        "messages": [response],
        "iteration_count": state["iteration_count"] + 1  # increment
    }

def tool_node(state: AgentState):
    # execute tools
    tool_results = tool_executor.invoke(state["messages"][-1])
    return {"messages": tool_results}

# --- Routing logic ---
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    
    # Check iteration limit FIRST
    if state["iteration_count"] >= state["max_iterations"]:
        print(f"⚠️ Max iterations ({state['max_iterations']}) reached!")
        return "end"
    
    # Check if agent wants to use tools
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    return "end"

# --- Build graph ---
workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "end": END
    }
)
workflow.add_edge("tools", "agent")

app = workflow.compile()

# --- Run ---
result = app.invoke({
    "messages": [HumanMessage(content="What is 25 * 4 + 100?")],
    "iteration_count": 0,
    "max_iterations": 5  # configurable per run
})
```

---

## 3. Graceful Fallback on Limit Exceeded

```python
from langchain_core.messages import AIMessage

def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    
    if state["iteration_count"] >= state["max_iterations"]:
        return "handle_limit"  # route to special node
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    
    return "end"

def handle_limit_node(state: AgentState):
    """Gracefully handle hitting the iteration limit."""
    return {
        "messages": [
            AIMessage(content=(
                "I've reached the maximum number of reasoning steps. "
                "Here's what I found so far based on my analysis..."
            ))
        ]
    }

workflow.add_node("handle_limit", handle_limit_node)
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "end": END,
        "handle_limit": "handle_limit"  # new route
    }
)
workflow.add_edge("handle_limit", END)
```

---

## 4. Using `RunnableConfig` for Dynamic Limits

```python
from langchain_core.runnables import RunnableConfig

def agent_node(state: AgentState, config: RunnableConfig):
    # Read limit from config at runtime
    max_iter = config.get("configurable", {}).get("max_iterations", 10)
    
    if state["iteration_count"] >= max_iter:
        return {
            "messages": [AIMessage(content="Reached step limit.")],
            "iteration_count": state["iteration_count"] + 1
        }
    
    response = llm_with_tools.invoke(state["messages"])
    return {
        "messages": [response],
        "iteration_count": state["iteration_count"] + 1
    }

# Pass limits dynamically
result = app.invoke(
    {"messages": [...], "iteration_count": 0},
    config={"configurable": {"max_iterations": 7}}
)
```

---

## 5. Complete Production Example

```python
from typing import TypedDict, Annotated, Literal
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool

# --- Tools ---
@tool
def search(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"

@tool  
def calculator(expression: str) -> str:
    """Calculate a math expression."""
    return str(eval(expression))

tools = [search, calculator]

# --- LLM ---
llm = ChatOpenAI(model="gpt-4o", temperature=0)
llm_with_tools = llm.bind_tools(tools)

# --- State ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    steps: int

MAX_STEPS = 10

# --- Nodes ---
def call_model(state: AgentState) -> AgentState:
    response = llm_with_tools.invoke(state["messages"])
    return {
        "messages": [response],
        "steps": state["steps"] + 1
    }

# --- Router ---
def route(state: AgentState) -> Literal["tools", "end", "limit_reached"]:
    if state["steps"] >= MAX_STEPS:
        return "limit_reached"
    
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    
    return "end"

def handle_limit(state: AgentState) -> AgentState:
    return {
        "messages": [AIMessage(
            content=f"Stopped after {state['steps']} steps. "
                    "Please refine your question for a more direct answer."
        )]
    }

# --- Graph ---
graph = StateGraph(AgentState)

graph.add_node("agent", call_model)
graph.add_node("tools", ToolNode(tools))
graph.add_node("limit_reached", handle_limit)

graph.set_entry_point("agent")
graph.add_conditional_edges("agent", route, {
    "tools": "tools",
    "end": END,
    "limit_reached": "limit_reached"
})
graph.add_edge("tools", "agent")
graph.add_edge("limit_reached", END)

app = graph.compile()

# --- Invoke ---
result = app.invoke(
    {"messages": [HumanMessage(content="Research quantum computing trends")],
     "steps": 0},
    config={"recursion_limit": 50}  # safety net
)

print(result["messages"][-1].content)
```

---

## Quick Comparison

| Approach | Graceful? | Configurable? | Complexity |
|---|---|---|---|
| `recursion_limit` | ❌ Raises error | ✅ Per run | Low |
| State counter + router | ✅ Yes | ✅ Yes | Medium |
| Graceful fallback node | ✅ Best | ✅ Yes | Medium |
| `RunnableConfig` dynamic | ✅ Yes | ✅ Per caller | Medium |

**Best practice:** Use **state counter + graceful fallback node** with `recursion_limit` as a safety net.