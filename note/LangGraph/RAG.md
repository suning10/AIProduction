# Summary

## rewrite Query

- why
  - users query is very broad or plain english, not specific 
  - Query have too few tokens
  - vocabulary missmatch 
  - multi-turn query
    - need context
    - eg. what is pricing 
    - prior turn ask about product x
- How
  - Use a lightweight classifier 
    - to **Save Tokens**
    - Simple, clear question 
    - Complex, vague question 
  - Rewrite 
    - Use LLM  
    - concurrent firing similar questions 
    - decompose the question 
      - summarize after gather all the information 
    - use LLM to answer the question 
      - use answer to do query
- Common Mistake
  - Rewrite completely different semantics 
    - validator to check similarity 


## Hybrid Search 

- BM25 + Vector Search
  - Vector search top k
  - BM25 rerank this top k 
  - RRF (Reciprocal Rank Fuse)