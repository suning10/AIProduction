# Summary
- CompiledStateGraph [compiled](#note-1-comiledstategraph)
  - Build 
- Command VS Conditioanal Edge [command](#note-2-command-vs-conditionaledge)
  - Command is more dynamic 
  - Args:
    - resume 
    - update
    - goto 

## Note 1: ComiledStateGraph

After Graph has been build, the compiled result
```python
from langgraph.graph import StateGraph

builder = StateGraph(MyState)
builder.add_node("node_a", node_a_fn)
builder.add_edge("node_a", "node_b")
...

graph = builder.compile()   # <-- returns a CompiledStateGraph
```

## Note 2: Command VS ConditionalEdge

- Command
  - Depend on current node's execution
    - eg. tool_call, end
  - Used with Designation to enable dynamic node selection
- Conditional Edge
  - Reusable
  - Need Routing logic

**Command**
```python
            # Determine next node based on whether there are tool calls
if isinstance(response_message, AIMessage) and response_message.tool_calls:
    goto = "tool_call"
else:
    goto = END

return Command(update={"messages": [response_message]}, goto=goto)

# inside graph creation
# destination can be a tuple or dict
# this enables dynamically determine which node to go next
# destination is commonly used with Command
graph_builder = StateGraph(GraphState)
graph_builder.add_node("chat", self._chat, destinations=("tool_call", END))
graph_builder.add_node(
    "tool_call",
    self._tool_call,
    destinations=("chat",),
    retry_policy=RetryPolicy(max_attempts=3),
)
graph_builder.set_entry_point("chat")
graph_builder.set_finish_point("chat")

```

**Conditional Edge

Routing
```python
def _route_after_chat(self, state: GraphState) -> str:
    # This is the piece that replaces destinations=("tool_call", END)
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tool_call"
    return END
```
Build Graph
```python
graph_builder = StateGraph(GraphState)
graph_builder.add_node("chat", self._chat)
graph_builder.add_node(
    "tool_call",
    self._tool_call,
    retry_policy=RetryPolicy(max_attempts=3),
)

graph_builder.set_entry_point("chat")

# Static edge: tool_call always goes back to chat — no branching needed here
graph_builder.add_edge("tool_call", "chat")

# Conditional edge: chat branches based on _route_after_chat's return value
graph_builder.add_conditional_edges(
    "chat",
    self._route_after_chat,
    {"tool_call": "tool_call", END: END},
)

```

## Note 3 Crate Graph

- Start
- Node
- Edge
- End
- Compile
  - Checkpointer
