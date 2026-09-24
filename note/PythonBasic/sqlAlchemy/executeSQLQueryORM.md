# Uer ORM
- summary 
  - [cheatsheet](#quick-reference-table)
  - use col for type safety 
    - [type safety](../../../app/services/database.py)
    - line 182, get user session

# SQLAlchemy Common Statements

## Setup & Connection

```python
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Session, relationship
from sqlalchemy import select, insert, update, delete, and_, or_, func

# Create engine
engine = create_engine("postgresql://user:password@localhost/dbname")
engine = create_engine("sqlite:///mydb.sqlite")
engine = create_engine("mysql+pymysql://user:password@localhost/dbname")

# Session
with Session(engine) as session:
    ...
```

---

## Model Definition

```python
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id       = Column(Integer, primary_key=True)
    name     = Column(String(50), nullable=False)
    email    = Column(String(100), unique=True)
    age      = Column(Integer, default=0)

    posts    = relationship("Post", back_populates="user")

class Post(Base):
    __tablename__ = "posts"

    id      = Column(Integer, primary_key=True)
    title   = Column(String(200))
    user_id = Column(Integer, ForeignKey("users.id"))

    user    = relationship("User", back_populates="posts")

# Create all tables
Base.metadata.create_all(engine)
```

---

## INSERT

```python
# Add one
user = User(name="Alice", email="alice@example.com")
session.add(user)
session.commit()

# Add many
session.add_all([
    User(name="Bob",   email="bob@example.com"),
    User(name="Carol", email="carol@example.com"),
])
session.commit()
```

---

## SELECT

```python
# Get all
users = session.execute(select(User)).scalars().all()

# Get by primary key
user = session.get(User, 1)

# Filter
user = session.execute(
    select(User).where(User.name == "Alice")
).scalar_one()

# Multiple conditions
users = session.execute(
    select(User).where(
        and_(User.age > 18, User.name.like("A%"))
    )
).scalars().all()

# OR condition
users = session.execute(
    select(User).where(
        or_(User.name == "Alice", User.name == "Bob")
    )
).scalars().all()

# Order, Limit, Offset
users = session.execute(
    select(User)
    .order_by(User.name.asc())
    .limit(10)
    .offset(20)
).scalars().all()

# Select specific columns
results = session.execute(
    select(User.name, User.email)
).all()

# First result
user = session.execute(select(User)).scalars().first()
```

---

## UPDATE

```python
# Update via ORM object
user = session.get(User, 1)
user.name = "Updated Name"
session.commit()

# Bulk update
session.execute(
    update(User)
    .where(User.age < 18)
    .values(age=18)
)
session.commit()
```

---

## DELETE

```python
# Delete via ORM object
user = session.get(User, 1)
session.delete(user)
session.commit()

# Bulk delete
session.execute(
    delete(User).where(User.name == "Bob")
)
session.commit()
```

---

## Aggregations

```python
from sqlalchemy import func

# Count
count = session.execute(select(func.count(User.id))).scalar()

# Sum, Avg, Min, Max
result = session.execute(
    select(
        func.sum(User.age),
        func.avg(User.age),
        func.min(User.age),
        func.max(User.age),
    )
).one()

# Group by
from sqlalchemy import func
results = session.execute(
    select(User.name, func.count(Post.id))
    .join(Post)
    .group_by(User.name)
).all()
```

---

## JOIN

```python
# Inner join
results = session.execute(
    select(User, Post)
    .join(Post, User.id == Post.user_id)
).all()

# Left outer join
results = session.execute(
    select(User, Post)
    .outerjoin(Post, User.id == Post.user_id)
).all()

# Using relationship
results = session.execute(
    select(User).join(User.posts)
).scalars().all()
```

---

## Subquery

```python
subq = select(func.avg(User.age)).scalar_subquery()

users = session.execute(
    select(User).where(User.age > subq)
).scalars().all()
```

---

## IN / NOT IN

```python
users = session.execute(
    select(User).where(User.name.in_(["Alice", "Bob"]))
).scalars().all()

users = session.execute(
    select(User).where(User.name.not_in(["Alice", "Bob"]))
).scalars().all()
```

---

## NULL Checks

```python
users = session.execute(
    select(User).where(User.email.is_(None))
).scalars().all()

users = session.execute(
    select(User).where(User.email.is_not(None))
).scalars().all()
```

---

## Transaction

```python
with Session(engine) as session:
    with session.begin():          # auto commit/rollback
        session.add(User(name="Dave"))

# Manual
try:
    session.add(User(name="Eve"))
    session.commit()
except Exception:
    session.rollback()
    raise
```

---

## Useful Extras

```python
# Check if exists
from sqlalchemy import exists

stmt = select(exists().where(User.email == "alice@example.com"))
exists_bool = session.execute(stmt).scalar()

# Distinct
users = session.execute(
    select(User.name).distinct()
).scalars().all()

# Raw SQL
from sqlalchemy import text
result = session.execute(
    text("SELECT * FROM users WHERE name = :name"),
    {"name": "Alice"}
).all()
```

---

## Quick Reference Table

| Operation | Method |
|-----------|--------|
| Insert | `session.add()` / `session.add_all()` |
| Select all | `select(Model)` |
| Filter | `.where(condition)` |
| Update | `update(Model).values()` |
| Delete | `delete(Model).where()` |
| Count | `func.count()` |
| Sort | `.order_by(col.asc/desc())` |
| Limit/Offset | `.limit(n).offset(n)` |
| Join | `.join(Model)` |
| Commit | `session.commit()` |
| Rollback | `session.rollback()` |