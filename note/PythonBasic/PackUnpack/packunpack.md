# Summary

## * vs **

- unpacking [unpack](#unpacking) - used when pass data to function 
  - \* unpack an iterable(tuple, list, string)
  - \** unpack an dict
- packing - used when define function 
  - \* pack extra args into tuple
  - \* pack extra args into dict

## unpacking
```python
def greet(name, age):
    print(f"Hello {name}, you are {age}.")

# Using * to unpack a list
user_list = ["Alice", 25]
greet(*user_list)    # Equivalent to greet("Alice", 25)

# Using ** to unpack a dictionary
user_dict = {"name": "Bob", "age": 30}
greet(**user_dict)  # Equivalent to greet(name="Bob", age=30)
```

## pack in function 
```python
def dynamic_function(*args, **kwargs):
    print(args)    # A tuple of positional arguments
    print(kwargs)  # A dictionary of keyword arguments

dynamic_function(1, 2, 3, a="apple", b="banana")
# Output:
# (1, 2, 3)
# {'a': 'apple', 'b': 'banana'}

```
    