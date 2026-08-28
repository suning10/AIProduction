# Summary

## asyncio command

- to fire concurrently - simple
  - asyncio.gather() [concurrent](../../FastAPI/concurrent.md)
- use a queue 
  - takes arrive dynamically [dynamic](#dynamic)
  - backpressure [backpressure](#backpressure)
  - Used for stream 
- when await is required
  - to get result (handle return) [wait for return](#wait-for-return)
  - to handle exception 
  - ensure task finish before moving on 
- when await is not needed
  - fire and forget [fire-forget](#fire-and-forget)
    - save to long term memory
    - write to log


### dynamic
```python
# Items trickle in from websocket, file, user input, etc.
async def producer(queue):
    async for message in websocket:        # never-ending stream
        await queue.put(message)

async def consumer(queue):
    while True:
        item = await queue.get()
        await process(item)
        queue.task_done()
```

### backpressure
```python

# maxsize blocks producer when queue is full
queue = asyncio.Queue(maxsize=10)   # ← producer will WAIT if 10 items pending

async def producer(queue):
    for item in huge_dataset:
        await queue.put(item)       # blocks here if queue full — backpressure!
```

### fire and forget
```python
openai_msgs = cast(list[dict], convert_to_openai_messages(response["messages"]))
asyncio.create_task(memory_service.add(user_id, openai_msgs, config.get("metadata")))
```

### must use await
```python
async def main():
    task = asyncio.create_task(fetch_data())
    result = await task   # must await to get return value
    print(result)

async def main():
    task1 = asyncio.create_task(fetch_data(1))
    task2 = asyncio.create_task(fetch_data(2))

    # Both already running concurrently here!

    result1 = await task1  # wait for task1
    result2 = await task2  # wait for task2 (likely already done)
```

### wait for return
```python
# step 2: get long-term Memory(or cache) -- use await to wait for result to be returned
state, relevant_memory = await asyncio.gather(
    graph.aget_state(config),
    memory_service.search(user_id, messages[-1].content),
)
```
