# Summary

# Concurrent vs Async

- Concurrent: [toolcall](../../app/core/langgraph/graph.py) line 210
  - Asyncio.gather()
    - fire all tasks at the same time
- Async and Await
  - Create a coroutine
    - while waiting on I/O or response won't freeze the event loop
    - still execute sequentially

Async and await
```python
for tool_call in llm_response.tool_calls:
    tool_result = await agent.execute_tool(...)   # <- suspends HERE
    messages.append(...)

t=0   call A starts, awaits
t=1   call A done -----> call B starts, awaits
t=2   call B done -----> call C starts, awaits
t=3   call C done
Total: 3 seconds
```

Concurrent
```python
async def execute_one(tool_call):
    if self.validator:
        validation_result = self.validator.validate_tool_call(
            agent.agent_id, tool_call.name
        )
        if not validation_result.get("valid"):
            logger.warning(f"⚠️ 约束警告: {validation_result.get('reason')}")

    tool_result = await agent.execute_tool(
        tool_name=tool_call.name,
        arguments=tool_call.arguments
    )
    return agent.llm_client.create_tool_message(
        tool_call_id=tool_call.id,
        tool_name=tool_call.name,
        result=tool_result
    )

results = await asyncio.gather(*(execute_one(tc) for tc in llm_response.tool_calls))
messages.extend(results)

t=0   call A starts, call B starts, call C starts (all scheduled)
t=1   all three finish (their waits overlapped)
Total: ~1 second
gather preserve the order and no locking is need as long as count++ before await
```
understand asyncio.gather()
- "*" means unpack
```python
# this equals to
coros = [execute_one(tc) for tc in llm_response.tool_calls]  # list comprehension instead of generator
results = await asyncio.gather(*coros)

#or

results = await asyncio.gather(
    execute_one(tool_calls[0]),
    execute_one(tool_calls[1]),
    execute_one(tool_calls[2]),
)
```
