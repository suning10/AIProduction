# use a container to config all dependencies (Spring IOC like)

- why:
  - Single place to config all dependencies 
  - easy access 
    - through app.state.container
  - singleton 
    - no need to create connection for every request 
      - container.db_pool
  - easy to manage lifecycle
    - start/shutdown 
  - cons 
    - no lazy loading (for rarely used services)
    - no scope - app level only
      - create per request vs app level 
        - need to separate clearly [scoped right way](#scoped-dependencies)

- how
  - start by building a container and ini in main.py
  - container = build_container(settings)
  - app.state.container = container
    

## scoped dependencies

```python
# ❌ Problem - request-scoped data leaking
class Container:
    current_user: User  # WRONG! this is per-request, not app-level

# ✅ Solution - separate app-level vs request-level
class Container:
    # App-level (singleton) - lives entire app lifetime
    db_pool: AsyncPool
    cache: Redis
    
# Request-level - created per request
async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme)
) -> User:
    return await decode_token(token)
```

## build container
```python
@dataclass
class Container:
    settings: Settings
    store: object
    session_store: object
```
```python
def build_container(settings: Optional[Settings] = None) -> Container:
    settings = settings or get_settings()

    mongo = MongoDB(settings)
    store = build_store(mongo)
    session_store = build_session_store(settings)
    job_queue = JobQueue(store, session_store, settings.async_stream_name)

    llm = DeepSeekClient(settings)
    relay = RelayClient(settings)
```