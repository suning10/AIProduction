# Summary

## what is map and reduce

- map, "Apply a function to every element"
- reduce: "Combine all elements into a single result"

map - reduce
```python
words = ["hello world", "foo bar", "hello foo"]

# Step 1 - MAP: split each string into words
mapped = list(map(str.split, words))
# [['hello', 'world'], ['foo', 'bar'], ['hello', 'foo']]

# Step 2 - REDUCE: flatten into one list
reduced = reduce(operator.add, mapped)
# ['hello', 'world', 'foo', 'bar', 'hello', 'foo']
```

