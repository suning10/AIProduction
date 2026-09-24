# Summary
- how to check db connection health
- use select 1 
- [example](../../../app/services/database.py) health_check

```python
session.exec(select(1)).first()
```