# Summary

## AsyncGenerator and Yield [generator](../PythonBasic/generator_function.md)

- Response Returns an asyncGenerator
  - use yield()
    - yield is a pull model
      - produce at its own speed [compare](#pull-vs-push)
- Enable in LLM side
  - graph.astream_events() -> most granular
  - graph.astream()
  - stream_mode="messages" -> token by token
- How to consume a generator function [example](#how-to-consume-a-generator-function-)
  - StreamingResponse itself has async for loop to consume generator function


### async for
- only useful when streaming
```python
async for token, _ in graph.astream(
    graph_input,
    config,
    stream_mode="messages",
):
    # filter anything not ai message , eg human
    if not isinstance(token, (AIMessage, AIMessageChunk)):
        continue

    text = extract_text_content(token.content)
    if text:
        yield text
```

### How to Consume a generator function
```python
async def event_generator():
    yield "data: Hello\n\n"
    yield "data: World\n\n"


# Option A — Pass to StreamingResponse (FastAPI consumes it)
@app.get("/stream")
async def stream():
    return StreamingResponse(
        event_generator(),        # ← pass generator object
        media_type="text/event-stream"
    )
    # StreamingResponse internally does async for on it


# Option B — Consume it yourself
@app.get("/collect")
async def collect():
    full_text = ""
    async for chunk in event_generator():   # ← you consume it
        full_text += chunk
    return {"text": full_text}
```


### pull vs push
```python
┌─────────────┬──────────────────────────┬──────────────────────────┐
│             │  PULL                    │  PUSH                    │
├─────────────┼──────────────────────────┼──────────────────────────┤
│ Control     │ Consumer drives          │ Producer drives          │
│ Example     │ Python async generator   │ Java Reactor Flux        │
│ Backpressure│ Automatic/implicit       │ Explicit handling needed │
│ Overwhelm   │ Impossible               │ Possible without BP      │
│ Code style  │ Sequential looking       │ Functional/reactive      │
│ Complexity  │ Simpler                  │ More complex             │
│ Best for    │ LLM streams, simple APIs │ High-throughput systems  │
└─────────────┴──────────────────────────┴──────────────────────────┘

Key insight:
  Both use long HTTP connections for SSE
  Push/Pull is about WHO controls the pace of data production
  For LLM streaming → Pull is simpler and works perfectly fine
  For high-volume data pipelines → Push with backpressure is better


# For LLM streaming specifically:
# Pull model works PERFECTLY because:

# 1. LLM generates tokens at its own pace anyway
# 2. Network sends them as they arrive
# 3. Client reads them as they arrive
# 4. No "fast producer overwhelming slow consumer" problem
#    because LLM tokens arrive SLOWER than we can process them

# The bottleneck is always the LLM, not the consumer

LLM (slow producer)    FastAPI (pull)     Browser (consumer)
       │                    │                   │
       │──token──▶          │                   │
       │                    │──chunk──▶          │
       │ (thinking...)      │                   │ (waiting)
       │──token──▶          │                   │
       │                    │──chunk──▶          │

# Browser is always waiting for LLM
# Never the other way around
# So backpressure is not a real concern here
```

```python
PULL (Python asyncio)              PUSH (Java Reactor)
──────────────────────────         ──────────────────────────

async def stream():                Flux.create(sink -> {
    yield "Hello"                      sink.next("Hello")
    yield " World"                     sink.next(" World")
    yield "!"                          sink.next("!")
                                       sink.complete()
                                   })

async for token in stream():       flux.subscribe(
    process(token)                     token -> process(token)
                                   )

Consumer calls __anext__()         Producer calls onNext()
Consumer drives timing             Producer drives timing
Generator frozen between yields    Subscriber reacts to emissions
Natural backpressure               Explicit backpressure handling
```
