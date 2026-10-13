# RRF (Reciprocal Rank Fusion)

## What is RRF?
**Reciprocal Rank Fusion** is a **rank aggregation algorithm** that combines multiple ranked lists of documents into a **single unified ranking** without needing scores from individual retrievers.

---

## The Formula

```
RRF_score(document) = Σ 1 / (k + rank(document))
```

Where:
- **k** = constant (usually **60**) to reduce impact of high rankings
- **rank** = position of document in each ranked list
- **Σ** = sum across all ranked lists

---

## Simple Example

### Step 1: Two different search results
```
Query: "What is machine learning?"

BM25 Results (keyword):      Vector Search Results:
1. Document A                1. Document C
2. Document B                2. Document A
3. Document C                3. Document D
4. Document D                4. Document B
```

### Step 2: Calculate RRF scores (k=60)
```
Document A:
  BM25   → rank 1 → 1/(60+1) = 0.0164
  Vector → rank 2 → 1/(60+2) = 0.0161
  Total  = 0.0325  ✅

Document B:
  BM25   → rank 2 → 1/(60+2) = 0.0161
  Vector → rank 4 → 1/(60+4) = 0.0156
  Total  = 0.0317

Document C:
  BM25   → rank 3 → 1/(60+3) = 0.0159
  Vector → rank 1 → 1/(60+1) = 0.0164
  Total  = 0.0323

Document D:
  BM25   → rank 4 → 1/(60+4) = 0.0156
  Vector → rank 3 → 1/(60+3) = 0.0159
  Total  = 0.0315
```

### Step 3: Final Ranking
```
1. Document A  (0.0325) ✅
2. Document C  (0.0323)
3. Document B  (0.0317)
4. Document D  (0.0315)
```

---

## Code Implementation

### From Scratch
```python
def reciprocal_rank_fusion(ranked_lists, k=60):
    """
    ranked_lists: list of lists containing document ids in ranked order
    k: constant (default=60)
    """
    scores = {}
    
    for ranked_list in ranked_lists:
        for rank, doc_id in enumerate(ranked_list, start=1):
            if doc_id not in scores:
                scores[doc_id] = 0
            scores[doc_id] += 1 / (k + rank)
    
    # Sort by score descending
    sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_docs

# Example
bm25_results    = ["doc_A", "doc_B", "doc_C", "doc_D"]
vector_results  = ["doc_C", "doc_A", "doc_D", "doc_B"]

final_ranking = reciprocal_rank_fusion([bm25_results, vector_results])
print(final_ranking)
# [('doc_A', 0.0325), ('doc_C', 0.0323), ('doc_B', 0.0317), ('doc_D', 0.0315)]
```

### With LangChain
```python
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS

# Create retrievers
bm25_retriever = BM25Retriever.from_documents(docs)
bm25_retriever.k = 10

vector_retriever = FAISS.from_documents(docs, embeddings).as_retriever(
    search_kwargs={"k": 10}
)

# Combine with RRF
ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.5, 0.5]  # Equal weight
)

results = ensemble_retriever.invoke("What is machine learning?")
```

### With LlamaIndex
```python
from llama_index.retrievers import BM25Retriever, VectorIndexRetriever
from llama_index.retrievers.fusion_retriever import QueryFusionRetriever

retriever = QueryFusionRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    similarity_top_k=10,
    mode="reciprocal_rerank",  # RRF mode
    num_queries=1
)

results = retriever.retrieve("What is machine learning?")
```

---

## Where RRF is Used

```
Hybrid Search Pipeline:

Query
  │
  ├──→ BM25 (Keyword Search)    → [ranked list 1]
  │                                      │
  ├──→ Vector Search (Semantic) → [ranked list 2]  ──→ RRF ──→ Final Results
  │                                      │
  └──→ Other Retriever          → [ranked list 3]
```

---

## RRF vs Other Fusion Methods

| Method | Description | Pros | Cons |
|---|---|---|---|
| **RRF** | Rank-based fusion | Simple, no score normalization needed | Ignores score magnitude |
| **Linear Combination** | Weighted score sum | Uses score info | Requires score normalization |
| **Reranker** | ML model rescoring | Most accurate | Slower, needs model |
| **Voting** | Majority vote | Simple | Less nuanced |

---

## Why RRF is Popular

| Feature | Detail |
|---|---|
| ✅ **Simple** | Easy to implement |
| ✅ **No normalization** | Scores from different systems don't need to be on same scale |
| ✅ **Robust** | Works well across different retrieval systems |
| ✅ **Effective** | Often beats individual retrievers |
| ✅ **No training** | No ML model needed |
| ❌ **Ignores scores** | Only uses rank position, not actual scores |

---

## Key Insight on K=60

```python
# Why k=60?
# Tested empirically - reduces impact of top ranks
# preventing any single list from dominating

k = 60
ranks = [1, 5, 10, 20, 50, 100]

for rank in ranks:
    score = 1 / (k + rank)
    print(f"Rank {rank:3d}: {score:.4f}")

# Rank   1: 0.0164
# Rank   5: 0.0154
# Rank  10: 0.0143
# Rank  20: 0.0125
# Rank  50: 0.0091
# Rank 100: 0.0063
```

---

## Summary

```
RRF = Simple + Effective way to combine multiple search results

Best used in:
✅ Hybrid Search (BM25 + Vector)
✅ Multiple retriever combination
✅ When scores are not comparable
✅ RAG pipelines
```