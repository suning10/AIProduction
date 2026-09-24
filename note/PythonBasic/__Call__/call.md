# when and what do __call__ do

- what:
  - __call__ lets an object be used like a function
- when
- It's useful when you need both:
- State (stored in __init__) — configured once
- Callable behavior (__call__) — executed per request/call





## what
```python
# Without __call__
class WithoutCall:
    def do_something(self):
        return "hello"

obj = WithoutCall()
obj()           # ❌ TypeError: object is not callable
obj.do_something()  # ✅ must call method explicitly


# With __call__
class WithCall:
    def __call__(self):
        return "hello"

obj = WithCall()
obj()           # ✅ works! triggers __call__
```

## when
```python
class AuthChecker:
    def __init__(self, role: str):
        self.role = role          # set at startup

    def __call__(self, user = Depends(get_current_user)):
        # runs every request
        if user.role != self.role:
            raise HTTPException(403, "Wrong role")
        return user

# Create instances with different configs
require_admin = AuthChecker(role="admin")
require_editor = AuthChecker(role="editor")

# Use like a function in Depends
@app.delete("/users")
async def delete_user(user = Depends(require_admin)):
    #                          ↑ require_admin(user) called automatically
    ...

@app.post("/posts")
async def create_post(user = Depends(require_editor)):
    ...
```