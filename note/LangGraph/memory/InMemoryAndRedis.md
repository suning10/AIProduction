# Summary

## How to create in-memory cache  [in-memory](#in-memory)

- init 
  - _cache: {key, tuple(**expire**, val)
  - ttl: int
- get
  - check if expire_ts > time.now 
- set
  - set both value + expire_at 

## how to create redis [redis](#redis)
- init 
  - redis_client
  - no
- get
  - **Redis Manage Expire through ttl automatically** 
- set
  - use async


### in-memory
```python
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Set a value in cache with TTL.

        Args:
            key: The cache key.
            value: The value to cache.
            ttl: Time-to-live in seconds. Uses default if not specified.
        """
        expires_at = time.monotonic() + (ttl or self._default_ttl)
        self._cache[key] = (expires_at, value)
```


### redis
```python
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        """Set a value in Valkey with TTL.

        Args:
            key: The cache key.
            value: The value to cache.
            ttl: Time-to-live in seconds. Uses default if not specified.
        """
        if not self._client:
            return
        try:
            await self._client.set(key, value, ex=(ttl or self._default_ttl))
        except Exception as e:
            logger.warning("cache_set_failed", key=key, error=str(e))
```