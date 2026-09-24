# Summary 
- why use default_factory 
  - Used by dynamic populate a field by a callable 
    - Calls a function to generate the default value
    - if use default, it will have all created_at the same
  - requires a callable function
    - use lambda [lambda](lambda.md)




```python
class BaseModel(SQLModel):
    """Base model with common fields."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

```python
# ❌ WRONG - evaluated ONCE at class definition time
# All instances share the same timestamp!
created_at: datetime = Field(default=datetime.now(UTC))

# ✅ CORRECT - evaluated each time a new instance is created
# Every instance gets its own fresh timestamp
created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```