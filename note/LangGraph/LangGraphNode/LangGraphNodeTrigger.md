# Summary 

## how do langgraph node's function get executed 

- use dependency injection by inspection node function signatures at runtime
- only execute when call invoke 
  - recall node function can only have two args [runningconfig](../Runnable/runnableconfig.md)
    - state
    - config



create node

```python
graph_builder.add_node("worker", self._worker, destinations=("synthesize",))
graph_builder.add_node("synthesize", self._synthesize, destinations=(END,))
```

```python
graph.compile()
    └─ Validates node signatures, wires up edges
    
graph.invoke(initial_state, config)
    └─ Execution starts
        ├─ Node "_worker" is reached
        │   └─ LangGraph inspects signature → injects (state, config) → calls it
        │
        └─ Node "_synthesize" is reached
            └─ LangGraph inspects signature → injects (state, config) → calls it
```

```python
graph = graph_builder.compile()

# Both state AND config are injected automatically when nodes execute
result = graph.invoke(
    {"messages": [...]},          # → becomes GraphState
    config={"configurable": {...}} # → becomes RunnableConfig
)
```
inspect node function and call, ** unpack a dict
```python
# LangGraph internally does something like this when calling a node:
import inspect

def _call_node(func, state, config):
    sig = inspect.signature(func)
    kwargs = {}
    
    for param_name, param in sig.parameters.items():
        if param.annotation == GraphState:  # or matches state type
            kwargs[param_name] = state
        elif param.annotation == RunnableConfig:
            kwargs[param_name] = config
    
    return func(**kwargs)
```