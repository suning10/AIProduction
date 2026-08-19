# Summary

## Intend-understanding

- Three Layer
  - Surface Layer
    - Re.match
      - do not create too broad list of words
  - semantic layer
    - embedding to vec db
      - not just embed arg string of node tools
      - need more than 1 example of use case
      - ways
        - more ways toward last runs
        - Rewrite (Most Common) [Rewrite](./RAG.md)
    - single query
      - direct embedding
    - multiple round
      - embedding the context
  - Use LLM to help classify
- Layer 1 and 2 should catch 90% of the case


## How to Embed

**store tools as object**
```python
{
  "tool_id": "cancel_subscription",
  "embedding_text": "Cancel subscription. Use when a user wants to stop, end, or cancel a recurring service. Examples: 'cancel my plan', 'I want to stop my subscription', 'end my membership'.",
  "metadata": {
    "params": ["user_id", "subscription_id"],
    "category": "billing"
  }
}
```
** Embed multiple per tool
```python
tool_id=cancel_subscription, vector=embed("cancel my plan")
tool_id=cancel_subscription, vector=embed("stop my subscription")
tool_id=cancel_subscription, vector=embed("I don't want to be charged anymore")
```

## optimize

- use cache
  - most of embeddings won't change
- embed before app start
