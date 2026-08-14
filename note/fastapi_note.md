from qdrant_client.auth import BearerAuthfrom app.core.logging import bind_context

## threadlocal vs ContextVar

- threadlocal: each request is a thread
- ContextVar: await - request within the same thread -> mess up with logging

How to Use ContextVar

```python
_request_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("request_context", default=None)


def bind_context(**kwargs: Any) -> None:
    """Bind context variables to the current request.

    Args:
        **kwargs: Key-value pairs to bind to the logging context
    """
    current = _request_context.get() or {}
    _request_context.set({**current, **kwargs})
```
In auth.py, when user login
```python
try:
    verify_password()
    bind_context(userid = user.id)
```
>set({**current, **kwargs})
>
> ** means convert it into a dict = > {userid: user.id}
>
> compare with * -> positional-argument
>
```python
def foo(*args):        # collects positional args into a tuple
    print(args)
foo(1, 2, 3)            # args == (1, 2, 3)
```

## Depends
```python
@router.post("/chat/stream")
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["chat_stream"][0])
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    session: Session = Depends(get_current_session),
):
    """Process a chat request using LangGraph with streaming response.
```
```python
async def get_current_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Session:
```
```python
security = HTTPBearer()

Class HTTPBearer:
    async def __call__(
        self, request: Request
    ) -> Optional[HTTPAuthorizationCredentials]:
```
> in this endpoint, Depends(get_current_session) will handle authorization.\
> get_current_seesion is depends on security.\
> HTTPBearer itself is a callable .\
> this create a signature and will let the function who trigger it

```text
  Look at security = HTTPBearer() (auth.py:48). HTTPBearer is itself a callable.\
  (it implements __call__(self, request: Request))..\
   When FastAPI resolves Depends(security), it inspects security.__call__'s signature and sees a parameter
  typed Request. That type — not a name, the literal starlette.requests.Request type — is special-cased by FastAPI: instead of looking for another Depends(...) to resolve it, FastAPI just hands over the actual incoming request
  object it already has in hand (it's the same object that triggered chat_stream in the first place).

  So the chain is:

  FastAPI receives the real Request object for this call
    → chat_stream(request: Request, ..., session=Depends(get_current_session))
          FastAPI resolves session by calling get_current_session(credentials=...)
              get_current_session(credentials=Depends(security))
                  FastAPI resolves credentials by calling security(request=...)
                      → here it injects the *same* Request object, because the
                        parameter is typed `Request` — no Depends needed for this one

  You never manually thread request through get_current_session → security — you didn't even need to write request: Request in chat_stream's own signature for this to work (though it's there anyway, for the rate limiter, since
  slowapi's @limiter.limit also needs it).
```
