# Summary

## generator function [example](#example)

- yield makes a function generator function
- generator function won't automatically run 
  - it returns a generator object
- the function call it will call __anext__()

### example
```python
# Any function with yield inside it becomes a GENERATOR FUNCTION
# Calling it returns a GENERATOR OBJECT automatically
# No explicit return needed

async def event_generator():
    yield "something"    # ← this one keyword transforms the whole function
    yield "another"
    yield "done"

# Calling it does NOT run the code inside
# It just returns a generator object
gen = event_generator()   # returns <async_generator object>
# Step 3: StreamingResponse receives the generator object
return StreamingResponse(
    event_generator(),     # ← passing the generator object
    media_type="text/event-stream"
)
# StreamingResponse will call __anext__() on it later
# THAT is when the body actually runs
```

