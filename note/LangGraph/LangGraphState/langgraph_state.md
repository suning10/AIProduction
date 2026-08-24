# Summary
- What is State [state](#Note-1:-State:-Memory passed between nodes )
- State vs Checkpointer [checkpointer](#Checkpointer-vs-State)
- State.next - Interrupt [state.next](#interrupt-production-statenext)

## Note 1: State: Memory passed between nodes 

- default is a typedict 
- can also use pydantic
  - use Annotated + add_messages(default **reducer**) -> append new messages to State
    - reducer: Left and Right 
      - current -> to be updated 
        - default is to override 
- State stores **all messages (TOOL + AI + Human)**
  - use state["messages"] to retrieve 
  - 

**Default**
```python
class State(TypedDict):
    name: str
    greeting: str

# 2. Nodes read from state and write back to state
def create_greeting(state):
    name = state["name"]              # READ from state
    return {"greeting": f"Hello, {name}!"}  # WRITE to state

def shout_greeting(state):
    greeting = state["greeting"]      # READ from state
    return {"greeting": greeting.upper()}   # WRITE to state
```

**Pydantic**
```python
from langgraph.graph.message import add_messages
class GraphState(BaseModel):
    """State definition for the LangGraph Agent/Workflow."""

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The messages in the conversation"
    )
    long_term_memory: str = Field(default="", description="The long term memory of the conversation")
```

**State Messages**
```python
state["messages"] = [
    HumanMessage(content="What is the weather in London?"),
    AIMessage(content="", tool_calls=[...]),
    ToolMessage(content="It's 15°C and cloudy", tool_call_id="123"),
    AIMessage(content="The weather in London is 15°C and cloudy.")
]
```

## Checkpointer-vs-State

- State:
  - Message only available through the run (Langgraph Cycle: Start -> END)
- Checkpointer 
  - persists between runs 
- HITL [HITL](#hitl)
  - State and Checkpointer work at the same time 
  - without checkpointer won't able to recover the message before human interrupt 
    - Checkpointer will save state before pause 
    - Call Resume 


**state**
```python
app = graph.compile()  # no checkpointer

# Run 1
result = app.invoke({"messages": [HumanMessage("Hi")]})

# Run 2 - has NO memory of Run 1
result = app.invoke({"messages": [HumanMessage("What did I just say?")]})
# AI has no idea what you said before ❌
```

**Checkpointer**
```python
checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)  # ✅ with checkpointer

config = {"configurable": {"thread_id": "user_123"}}

# Run 1
result = app.invoke({"messages": [HumanMessage("Hi, I'm Alice")]}, config)

# Run 2 - REMEMBERS previous conversation
result = app.invoke({"messages": [HumanMessage("What's my name?")]}, config)
# AI knows your name is Alice ✅
```

### HITL
```text
Run starts
    ↓
State carries messages during execution
    ↓
Node runs → AIMessage added to state
    ↓
Interrupt hit → Checkpointer SAVES state (with all messages) 💾
    ↓
Graph PAUSES ⏸️
    ↓
Human reviews / inputs
    ↓
Resume called → Checkpointer LOADS saved state (restores all messages) 📂
    ↓
Graph CONTINUES with all previous messages still there
    ↓
END
```

## Interrupt-Production-State.Next

- 2 phase check [2-phase](#2--phase) 
  - check if previously interrupted 
  - Check if current loop runs into interruption 
- why state.next work [demo](#demo-of-next)
  - if not interrupted, it will return a empty tuple
  - else it will return a tuple of node to be run next 


### 2- phase
```text
User sends message
       ↓
Get state + Search memory (PARALLEL) ⚡
       ↓
Is graph paused? (state.next)
   YES → Resume with user's message
   NO  → Start fresh with relevant memory injected
       ↓
Graph runs...
       ↓
Did graph pause again? (state.next)
   YES → Return interrupt question to user ⏸️
   NO  → Return final answer + save to memory in background
```
````python
if state.next:
    logger.info("resuming_interrupted_graph", session_id=session_id, next_nodes=state.next)
    response = await graph.ainvoke(
        Command(resume=messages[-1].content),
        config=config,
    )
else:
    relevant_memory = relevant_memory or "No relevant memory found."
    response = await graph.ainvoke(
        input={"messages": dump_messages(messages), "long_term_memory": relevant_memory},
        config=config,
    )

# Check if the graph was interrupted during this invocation
state = await graph.aget_state(config)
if state.next:
    interrupt_value = state.tasks[0].interrupts[0].value if state.tasks else "Waiting for input."
    logger.info("graph_interrupted", session_id=session_id, interrupt_value=str(interrupt_value))
    return [Message(role="assistant", content=str(interrupt_value))]

````

### demo-of-next
```python
# state.next = tuple of nodes WAITING to run
# If graph finished normally → empty tuple () = falsy
# If graph is interrupted   → has node name = truthy

if state.next:  # truthy = interrupted ⏸️
    # resume
else:           # falsy = finished ✅
    # start fresh
```