# Summary

Generator is a simple way to create iterator using yield 
- iterator 
  - class with __next__
- Genertor
  - Function with yield 

when to use Generator [when to use](#when-to-use)


```python
# Same behavior, different implementation

# --- Iterator (manual) ---
class Squares:
    def __init__(self, n):
        self.i = 0
        self.n = n
    def __iter__(self): return self
    def __next__(self):
        if self.i >= self.n:
            raise StopIteration
        result = self.i ** 2
        self.i += 1
        return result

# --- Generator (simple) ---
def squares(n):
    for i in range(n):
        yield i ** 2

# Both work identically:
for x in Squares(4):   print(x)  # 0 1 4 9
for x in squares(4):   print(x)  # 0 1 4 9

# another way to call
square = squares(5)
print(next(square))
```

## when to use

## No! Generators Have Many Use Cases

Streaming is just **one** of many use cases. The core benefit of generators is **lazy evaluation** — producing values one at a time instead of all at once.

---

### 1. Memory Efficiency (Large Data)

```python
# ❌ Bad — loads ALL lines into memory at once
def read_file(path):
    with open(path) as f:
        return f.readlines()   # 10GB file = 10GB in RAM

# ✅ Good — yields one line at a time
def read_file(path):
    with open(path) as f:
        for line in f:
            yield line         # only 1 line in RAM at a time

for line in read_file("huge_file.txt"):
    process(line)
```

---

### 2. Infinite Sequences

```python
# Can't store infinite list — but generator handles it fine
def fibonacci():
    a, b = 0, 1
    while True:       # infinite loop is OK!
        yield a
        a, b = b, a + b

fib = fibonacci()
print(next(fib))  # 0
print(next(fib))  # 1
print(next(fib))  # 1
print(next(fib))  # 2
# ... forever, without memory issues
```

---

### 3. Pipeline / Chaining Operations

```python
# Each step is lazy — nothing runs until you consume
def read_logs(path):
    for line in open(path):
        yield line

def filter_errors(lines):
    for line in lines:
        if "ERROR" in line:
            yield line

def parse(lines):
    for line in lines:
        yield line.strip().upper()

# Building a pipeline — nothing executes yet
pipeline = parse(filter_errors(read_logs("app.log")))

# NOW it executes, one item at a time
for entry in pipeline:
    print(entry)
```

---

### 4. Generating Combinations / Permutations

```python
def pairs(items):
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            yield (items[i], items[j])

for pair in pairs([1, 2, 3, 4]):
    print(pair)
# (1,2), (1,3), (1,4), (2,3), (2,4), (3,4)
```

---

### 5. Generator Expressions (like list comprehensions)

```python
numbers = [1, 2, 3, 4, 5]

# List comprehension — builds full list in memory
squares_list = [x**2 for x in numbers]        # [1, 4, 9, 16, 25]

# Generator expression — lazy, one at a time
squares_gen  = (x**2 for x in numbers)        # <generator object>

# Useful in functions like sum, max, any, all
total = sum(x**2 for x in range(1_000_000))   # no giant list created!
```

---

### 6. State Machines

```python
def traffic_light():
    while True:
        yield "🟢 GREEN"
        yield "🟡 YELLOW"
        yield "🔴 RED"

light = traffic_light()
print(next(light))  # 🟢 GREEN
print(next(light))  # 🟡 YELLOW
print(next(light))  # 🔴 RED
print(next(light))  # 🟢 GREEN (cycles forever)
```

---

### 7. Streaming (Your Original Context)

```python
async def stream_tokens(graph, input):
    async for token, metadata in graph.astream(input):
        yield token   # send to client as produced, don't wait for all
```

---

### Summary of Use Cases

| Use Case | Why Generator? |
|---|---|
| Large files | Avoid loading all into memory |
| Infinite sequences | Can't store infinite data |
| Pipelines | Lazy chaining of operations |
| Combinations | Avoid huge intermediate lists |
| State machines | Natural pause/resume behavior |
| Streaming | Send data as it's produced |
| `sum/any/all` | No need to build full list |

---

### The Core Idea

```
Generator = Lazy Evaluation

Instead of:  compute ALL → store ALL → use ALL
You get:     compute ONE → use ONE → compute ONE → use ONE ...
```

> **Streaming** is just lazy evaluation applied to **network/IO output**. The same principle applies anywhere you want to process data **one piece at a time**.
