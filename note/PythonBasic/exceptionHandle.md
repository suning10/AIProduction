# Summary

## add more context to the exception

- use Raise RuntimeError("detailed and customized error message")

## bare raise
- show the exception message
```python
# WITHOUT bare raise — exception is SWALLOWED (bad)
except (RateLimitError, APITimeoutError, APIError) as e:
    logger.warning("llm_call_failed_retrying", ...)
    # execution continues normally — caller never knows it failed!

# WITH bare raise — exception is logged AND propagated (correct)
except (RateLimitError, APITimeoutError, APIError) as e:
    logger.warning("llm_call_failed_retrying", ...)
    raise  # caller still receives the exception
```