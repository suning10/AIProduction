# Summary

- what is Lambda
- when to use lambda


## Lambda Functions in Python

---

### What is a Lambda?

```python
# Regular function
def add(x, y):
    return x + y

# Same thing as lambda
add = lambda x, y: x + y

print(add(3, 4))  # 7
```

**Lambda is just a short, anonymous (no-name) function written in one line.**

---

### Syntax

```python
lambda arguments : expression
#      what goes in   what comes out (auto-returned)
```

```python
lambda x: x * 2          # one argument
lambda x, y: x + y       # two arguments
lambda: datetime.now()    # no arguments
lambda x: x if x > 0 else 0   # with condition
```

> ⚠️ Lambda can only have **one expression** — no multiple lines, no statements

---

### Regular Function vs Lambda

```python
# These are identical ✅

# Regular
def square(x):
    return x * x

# Lambda
square = lambda x: x * x

print(square(5))  # 25
```

---

## When To Use Lambda

---

### ✅ 1. Short, Throwaway Functions (most common)

```python
numbers = [3, 1, 4, 1, 5, 9, 2]

# Without lambda
def get_doubled(x):
    return x * 2

result = list(map(get_doubled, numbers))

# With lambda — cleaner, no need to define a whole function
result = list(map(lambda x: x * 2, numbers))

print(result)  # [6, 2, 8, 2, 10, 18, 4]
```

---

### ✅ 2. Sorting with Custom Key

```python
people = [
    {"name": "Alice", "age": 30},
    {"name": "Bob", "age": 25},
    {"name": "Charlie", "age": 35},
]

# Sort by age
sorted_people = sorted(people, key=lambda person: person["age"])
# [Bob(25), Alice(30), Charlie(35)]

# Sort by name length
sorted_by_name = sorted(people, key=lambda person: len(person["name"]))
# [Bob, Alice, Charlie]
```

---

### ✅ 3. `map()` — Transform Each Item

```python
prices = [10, 20, 30, 40]

# Apply 10% discount to each
discounted = list(map(lambda price: price * 0.9, prices))
print(discounted)  # [9.0, 18.0, 27.0, 36.0]

# Convert to strings
as_strings = list(map(lambda x: f"${x}", prices))
print(as_strings)  # ['$10', '$20', '$30', '$40']
```

---

### ✅ 4. `filter()` — Keep Matching Items

```python
numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

evens     = list(filter(lambda x: x % 2 == 0, numbers))
odds      = list(filter(lambda x: x % 2 != 0, numbers))
big_nums  = list(filter(lambda x: x > 5, numbers))

print(evens)     # [2, 4, 6, 8, 10]
print(odds)      # [1, 3, 5, 7, 9]
print(big_nums)  # [6, 7, 8, 9, 10]
```

---

### ✅ 5. `default_factory` in Pydantic / dataclasses

```python
from pydantic import BaseModel, Field
from datetime import datetime, UTC

class User(BaseModel):
    name: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: list  = Field(default_factory=lambda: [])  # fresh list each time
    meta: dict  = Field(default_factory=lambda: {})  # fresh dict each time
```

---

### ✅ 6. Callbacks / Event Handlers

```python
# GUI button click
button.on_click(lambda event: print("clicked!"))

# Quick callback
def run_operation(value, operation):
    return operation(value)

result = run_operation(10, lambda x: x ** 2)
print(result)  # 100
```

---

### ✅ 7. Conditional Logic (Ternary)

```python
clamp = lambda x, min_val, max_val: max(min_val, min(x, max_val))

print(clamp(15, 0, 10))   # 10
print(clamp(-5, 0, 10))   # 0
print(clamp(7,  0, 10))   # 7
```

---

## When NOT to Use Lambda

---

### ❌ Complex Logic — Use a Regular Function

```python
# Bad — hard to read
process = lambda x: x * 2 if x > 0 else x * -1 if x < 0 else "zero"

# Good — clear and readable
def process(x):
    if x > 0:
        return x * 2
    elif x < 0:
        return x * -1
    else:
        return "zero"
```

---

### ❌ Reusing Multiple Times — Give it a Name

```python
# Bad — lambda assigned to variable and reused
double = lambda x: x * 2  # just use def at this point

# Good
def double(x):
    return x * 2
```

---

### ❌ Multiple Steps Needed

```python
# Lambda can't do this (multiple lines)
# Bad attempt ❌
transform = lambda x: (
    x = x * 2      # SyntaxError!
    x = x + 1
    return x
)

# Good ✅
def transform(x):
    x = x * 2
    x = x + 1
    return x
```

---

## Quick Reference Cheat Sheet

```python
# No args
lambda: 42

# One arg
lambda x: x * 2

# Two args
lambda x, y: x + y

# Default arg
lambda x, y=10: x + y

# Conditional
lambda x: "even" if x % 2 == 0 else "odd"

# With method call
lambda s: s.strip().lower()

# Chained
lambda x: x * 2 + 1

# Used immediately (IIFE)
(lambda x: x * 2)(5)   # 10
```

---

## Summary

| Use Lambda When | Use `def` When |
|----------------|----------------|
| One-liner logic | Multiple lines needed |
| Used once / throwaway | Reused multiple times |
| As argument to another function | Needs a docstring |
| `map`, `filter`, `sorted` keys | Complex logic |
| `default_factory` callbacks | Easier to test/debug |

**Rule of thumb:** If you find yourself naming a lambda → use `def` instead.