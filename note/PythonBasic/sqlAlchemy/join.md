# how to use join


## left join
```python
select(LEFT_TABLE, RIGHT_TABLE)
.outerjoin(RIGHT_TABLE, ...)
```

## innerjoin
```python
# INNER JOIN - only users WITH posts
select(User, Post).join(Post, User.id == Post.user_id)
# Alice, Bob  ← only matched rows
```