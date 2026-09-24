# Writing Raw SQL in SQLAlchemy

## Using `text()` - Most Common Way

```python
from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///mydb.sqlite")
```

---

## SELECT

```python
with engine.connect() as conn:

    # Basic query
    result = conn.execute(text("SELECT * FROM users"))
    rows = result.all()

    # Fetch methods
    rows   = result.all()         # all rows as list
    row    = result.first()       # first row only
    row    = result.one()         # exactly one row (error if not)
    scalar = result.scalar()      # single value

    # With parameters (use :param syntax)
    result = conn.execute(
        text("SELECT * FROM users WHERE name = :name AND age > :age"),
        {"name": "Alice", "age": 18}
    )

    # Loop through rows
    for row in result:
        print(row)           # tuple-like
        print(row.name)      # access by column name
        print(row[0])        # access by index
        print(row._mapping)  # as dict
```

---

## INSERT

```python
with engine.connect() as conn:

    # Single insert
    conn.execute(
        text("INSERT INTO users (name, email) VALUES (:name, :email)"),
        {"name": "Alice", "email": "alice@example.com"}
    )

    # Bulk insert (pass list of dicts)
    conn.execute(
        text("INSERT INTO users (name, email) VALUES (:name, :email)"),
        [
            {"name": "Bob",   "email": "bob@example.com"},
            {"name": "Carol", "email": "carol@example.com"},
        ]
    )

    conn.commit()
```

---

## UPDATE

```python
with engine.connect() as conn:

    conn.execute(
        text("UPDATE users SET age = :age WHERE name = :name"),
        {"age": 30, "name": "Alice"}
    )

    conn.commit()
```

---

## DELETE

```python
with engine.connect() as conn:

    conn.execute(
        text("DELETE FROM users WHERE name = :name"),
        {"name": "Alice"}
    )

    conn.commit()
```

---

## With Session (ORM Session + Raw SQL)

```python
from sqlalchemy.orm import Session

with Session(engine) as session:

    result = session.execute(
        text("SELECT * FROM users WHERE age > :age"),
        {"age": 18}
    )

    rows = result.all()
    session.commit()
```

---

## Row to Dictionary

```python
with engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM users"))

    # Method 1 - _mapping
    for row in result:
        d = dict(row._mapping)
        print(d)  # {'id': 1, 'name': 'Alice', ...}

    # Method 2 - keys()
    rows = result.all()
    keys = result.keys()
    dicts = [dict(zip(keys, row)) for row in rows]
```

---

## Transaction

```python
with engine.connect() as conn:
    with conn.begin():            # auto commit/rollback
        conn.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": "Dave"})
        conn.execute(text("UPDATE users SET age = 25 WHERE name = :name"), {"name": "Dave"})

# Manual transaction
with engine.connect() as conn:
    try:
        conn.execute(text("INSERT INTO users (name) VALUES (:name)"), {"name": "Eve"})
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
```

---

## Complex Queries

```python
with engine.connect() as conn:

    # JOIN
    result = conn.execute(text("""
        SELECT u.name, p.title
        FROM users u
        JOIN posts p ON u.id = p.user_id
        WHERE u.age > :age
    """), {"age": 18})

    # Subquery
    result = conn.execute(text("""
        SELECT * FROM users
        WHERE age > (SELECT AVG(age) FROM users)
    """))

    # Aggregation
    result = conn.execute(text("""
        SELECT name, COUNT(*) as post_count
        FROM users u
        JOIN posts p ON u.id = p.user_id
        GROUP BY u.name
        ORDER BY post_count DESC
        LIMIT :limit
    """), {"limit": 10})
```

---

## ⚠️ Never Do String Formatting (SQL Injection Risk)

```python
# ❌ BAD - SQL Injection risk
name = "Alice"
conn.execute(text(f"SELECT * FROM users WHERE name = '{name}'"))

# ✅ GOOD - Use parameters
conn.execute(
    text("SELECT * FROM users WHERE name = :name"),
    {"name": name}
)
```

---

## Quick Reference

| Task | Code |
|------|------|
| Raw query | `text("SELECT ...")` |
| Named param | `:param_name` |
| Pass params | `{"param_name": value}` |
| All rows | `.all()` |
| First row | `.first()` |
| One row | `.one()` |
| Single value | `.scalar()` |
| Row as dict | `dict(row._mapping)` |
| Commit | `conn.commit()` |