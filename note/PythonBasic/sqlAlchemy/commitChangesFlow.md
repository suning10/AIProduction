# Summary


[referece_file](../../../app/services/database.py) -- line 81
- when commit changes, SQL automatically expire the object
  - No new data will be able to retrieve
  - must use refresh after commit 
```python
with Session(self.engine) as session:
    user = User(email=email, password=password, username=username)
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info(f"User created: {email}")
    return user
```

