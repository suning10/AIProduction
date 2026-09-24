# Dependency Injection 

- use depends 
  - key difference between SpringBoot and FastAPI
    - Fast API do not have IOC to inject Singleton and then call
    - FastAPI Depends take a callable and **return the callable results back**



```markdown
Depends is a class that takes a callable (like a function or a class) and tells FastAPI.\
to execute that callable before running your endpoint. FastAPI automatically resolves any.\
arguments the callable needs, executes it, and passes the returned value directly into .\
your route function
```

```python
from fastapi import FastAPI, Depends

app = FastAPI()

# 1. Define the dependency function
def pagination_params(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}

# 2. Inject it into an endpoint using Depends
@app.get("/items/")
async def read_items(commons: dict = Depends(pagination_params)):
    # The 'commons' variable automatically contains the dictionary returned by pagination_params
    return {"message": "Fetching data", "pagination": commons}
```

```python
security = HTTPBearer()
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
```

## Why Use `Depends` Instead of Direct Call?

You're right, you **technically can** just call it directly. But here's what you lose:

---

### 1. 🔁 Reusability Across Routes

**Without Depends — repeating yourself**
```python
@app.get("/users")
async def get_users():
    credentials = await security(request)  # have to pass request
    token = credentials.credentials
    user = validate_token(token)           # repeated everywhere
    # actual logic...

@app.get("/orders")
async def get_orders():
    credentials = await security(request)  # copy pasted
    token = credentials.credentials
    user = validate_token(token)           # copy pasted
    # actual logic...
```

**With Depends — declare once, use everywhere**
```python
async def get_current_user(credentials = Depends(security)):
    return validate_token(credentials.credentials)

@app.get("/users")
async def get_users(user = Depends(get_current_user)):  # clean
    ...

@app.get("/orders")  
async def get_orders(user = Depends(get_current_user)):  # clean
    ...
```

---

### 2. 🧪 Testability — Override Dependencies

This is probably the **biggest reason**

```python
# Your real dependency
async def get_current_user(credentials = Depends(security)):
    return validate_token(credentials.credentials)

# In tests — swap it out completely, no need for real tokens
app.dependency_overrides[get_current_user] = lambda: {"user": "test_user"}

def test_get_users():
    response = client.get("/users")  # no auth header needed!
    assert response.status_code == 200
```

**Without Depends**, you'd have to mock at a much lower level, patching internals — messy.

---

### 3. 📄 Automatic Swagger UI Integration

```python
security = HTTPBearer()

# FastAPI KNOWS this route needs auth because of Depends
@app.get("/protected")
async def protected(credentials = Depends(security)):
    ...
```

**FastAPI automatically adds:**
- 🔒 Lock icon on the route
- "Authorize" button in Swagger UI
- `401`/`403` in the response schema

If you call `security()` manually inside, Swagger has **no idea** auth is needed.

---

### 4. ⛓️ Dependency Chaining

```python
# Dependencies can depend on each other
async def get_db():
    db = SessionLocal()
    yield db
    db.close()

async def get_current_user(credentials = Depends(security)):
    return validate_token(credentials.credentials)

async def get_admin_user(
    user = Depends(get_current_user),  # chains from get_current_user
    db = Depends(get_db)
):
    if not user.is_admin:
        raise HTTPException(403)
    return user

# Route only cares about final result
@app.delete("/users/{id}")
async def delete_user(admin = Depends(get_admin_user)):
    ...
```

---

### 5. ⚡ Request-level Caching

```python
# If multiple routes/dependencies call Depends(get_db)
# FastAPI only creates ONE db session per request
# Direct calls would create multiple sessions!

async def get_users(db = Depends(get_db)):    # same db instance
async def get_orders(db = Depends(get_db)):   # same db instance
```

---

### Summary

| Reason | Direct Call | `Depends` |
|--------|------------|-----------|
| Reuse across routes | ❌ Copy paste | ✅ Declare once |
| Test overrides | ❌ Hard to mock | ✅ `dependency_overrides` |
| Swagger docs/auth UI | ❌ Invisible | ✅ Automatic |
| Chaining dependencies | ❌ Messy | ✅ Clean |
| Request-level caching | ❌ Multiple calls | ✅ Runs once |

> **Short answer:** Direct calls work for **one route**. `Depends` is for **maintainable, testable, documented** code across many routes.