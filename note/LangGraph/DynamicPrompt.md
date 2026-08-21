# Summary

## how to dynamically load system prmopt

- user specific long term memory
- agent name 
- current_date_time
- user context 

## use format to load template dynamically at runtime [format](#format)
- slower and heavier cost as it involves function call
- f is preferred 


```makefile
# Name: {agent_name}
# Role: A world class assistant
Help the user with their questions.

# Instructions
- Always be friendly and professional.
- If you don't know the answer, say you don't know. Don't make up an answer.
- Try to give the most accurate answer possible.

{user_context}
# What you know about the user
{long_term_memory}

# Current date and time
{current_date_and_time}
```
```python
with open(os.path.join(_PROMPTS_DIR, "system.md"), "r") as _f:
    _SYSTEM_PROMPT_TEMPLATE = _f.read()

with open(os.path.join(_PROMPTS_DIR, "session_title.md"), "r") as _f:
    SESSION_TITLE_PROMPT = _f.read()


def load_system_prompt(username: Optional[str] = None, **kwargs):
    """Load the system prompt from the cached template."""
    user_context = f"# User\nYou are talking to {username}.\n" if username else ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=settings.PROJECT_NAME + " Agent",
        current_date_and_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_context=user_context,
        **kwargs,
    )

```
```python
# call it like
SYSTEM_PROMPT = load_system_prompt(username = username, long_term_memory = state.long_term_memory)
```


### format
```python
name = "Alice"
age = 30

# Positional arguments
print("My name is {} and I am {} years old.".format(name, age))

# Keyword/Named arguments
print("My name is {n} and I am {a} years old.".format(n=name, a=age))

```