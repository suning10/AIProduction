# Summary

- abstract class 
  - can not ini
  - must implement all abstract method
- shortcut to use abstract class
- abc.ABC

```python

class RunBackend(abc.ABC):
    """Storage for run events, run metadata and the per-session lease."""

    name: str
    lock_ttl: float

    async def initialize(self) -> None:
        """Connect / prepare the backend."""

    async def close(self) -> None:
        """Release backend resources."""

    @abc.abstractmethod
    async def acquire(self, session_id: str, run_id: str, trigger_hash: str) -> Optional[str]:
        """Claim the session's single run slot and create the run.

        Returns:
            ``None`` if this call now owns the slot, otherwise the ``run_id`` currently holding it.
        """

    @abc.abstractmethod
    async def renew(self, session_id: str, run_id: str) -> bool:
        """Extend the lease (and the data's lifetime) if ``run_id`` still holds it."""

class ValkeyRunBackend(RunBackend):
    """Redis/Valkey backend: one Stream per run (``run:{id}:events``), a hash for metadata, a lease key per session.

    Uses its own client and pool: followers hold a connection for the length of each blocking ``XREAD``, which
    must not starve the cache's pool.
    """
```
