# Summary

## how to use annotated

- default = value vs default_factory = list
- Annotated[list, add_messages]
- Annotated[list[str], operator.add]
  - Operator.add or add_messages serve as a reducer (merge into one result) [reducer](../../PythonBasic/BasicOpertaion/mapReduce.md)
  - w/o reducer, when new reuslt come in, it will **override**

```python
    subtask_results: Annotated[list[str], operator.add] = Field(
        default_factory=list, description="Worker outputs, merged across parallel branches"
    )

    messages: Annotated[list, add_messages] = Field(
        default_factory=list, description="The messages in the conversation"
    )
```