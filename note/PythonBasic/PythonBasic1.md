## In This File 

- ClassMethod 
  - cls -> access to class itself
  - alternative constructor -> factory pattern
- Next 
  - Sugar: set default value if not found
- TypeVar
  - Used for type check 
- Python Minheap, maxheap
  - use heappush, heappop for minheap
  - for max heap, push negative value


### Python @classmethod

- No instance is neede
```python
class Person:
    species = "Human"  # Class variable

    def __init__(self, name, age):
        self.name = name
        self.age = age

    @classmethod
    def get_species(cls):
        return cls.species  # Access class variable

# Can be called on the class itself (no instance needed)
print(Person.get_species())  # Output: Human

# Can also be called on an instance
p = Person("Alice", 30)
print(p.get_species())       # Output: Human
```
- Usuallly used in Alternative construct
```python
LLMS: List[Dict[str, Any]] = []
    @classmethod
    def get(cls, model_name: str, **kwargs) -> BaseChatModel:
        model_entry = next((e for e in cls.LLMS if e["name"] == model_name), None)

        if not model_entry:
            available = ", ".join(e["name"] for e in cls.LLMS)
            raise ValueError(f"model '{model_name}' not found in registry. available models: {available}")

        if kwargs:
            logger.debug("creating_llm_with_custom_args", model_name=model_name, custom_args=list(kwargs.keys()))
            return langchain_openai.ChatOpenAI(model=model_name, api_key=_API_KEY, **kwargs)

        logger.debug("using_default_llm_instance", model_name=model_name)
        return model_entry["llm"]
        
```

```python
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

    @classmethod
    def from_string(cls, person_string):
        """Create a Person from a string like 'Alice-30'"""
        name, age = person_string.split("-")
        return cls(name, int(age))  # Creates a new instance

    @classmethod
    def from_dict(cls, data):
        """Create a Person from a dictionary"""
        return cls(data["name"], data["age"])

# Usage
p1 = Person("Alice", 30)                        # Normal way
p2 = Person.from_string("Bob-25")               # Alternative constructor
p3 = Person.from_dict({"name": "Charlie", "age": 35})

print(p2.name, p2.age)  # Bob 25
print(p3.name, p3.age)  # Charlie 35
```

#### Difference between self 

self refer to the instance while cls refer to the class .\
in the example above, LLM = ""... which is a class variable (BluePoint)


### Note 2:
> Python Next: next(condition, default)
> 
> *Cleaner version of get default value if not match*
> 
> Eg. ***ext((e for e in cls.LLMS if e["name"] == model_name), None)**

```python
# ❌ Verbose way (same result)
model_entry = None
for e in cls.LLMS:
    if e["name"] == model_name:
        model_entry = e
        break  # Stop after first match

# ✅ Clean one-liner (same result)
model_entry = next((e for e in cls.LLMS if e["name"] == model_name), None)
```


### note3
#### Typevar: 
> **use bound when need to ensure the data type**
```python
T = TypeVar("T", bound=BaseModel)
class UserModel(BaseModel):
    name: str
    age: int

class PostModel(BaseModel):
    title: str
    content: str

def parse_data(data: dict, model: Type[T]) -> T:
    return model(**data)


# Each call resolves T differently
user = parse_data({"name": "Alice", "age": 30}, UserModel)
#     ^^^^ T = UserModel here
#          return type = UserModel

post = parse_data({"title": "Hello", "content": "World"}, PostModel)
#     ^^^^ T = PostModel here
#          return type = PostModel

print(type(user))  # <class 'UserModel'>
print(type(post))  # <class 'PostModel'>
```

# Note 4
## python multi-dimension array
```python
dp = [[0] * cols for _ in range(rows)]

# wrong way- only copy the reference 
dp = [[0] * cols] * rows 
dp[0][0] = 99
print(dp)  # [[99,0,0,0], [99,0,0,0], [99,0,0,0]] - ALL rows changed!
```

## python min heap

```python
import heapq

heap = []
heappush(heap, num)
heappop()

# NLargest
heappush(heap, num)
if len(heap) > k:
    heappop()

# one line
heapq.nlargest(k, nums)
# max heap -> use negative

custom sort 

```

## python default dict
```python
from collections import defaultdict
hashmap = defaultdict(int)
```