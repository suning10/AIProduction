# Summary

## asyncio command

- to fire concurrently - simple
  - asyncio.gather() [concurrent](../FastAPI/concurrent.md)
- use a queue 
  - takes arrive dynamically [dynamic](#dynamic)
  - backpressure [backpressure](#backpressure)
  - Used for stream 



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

