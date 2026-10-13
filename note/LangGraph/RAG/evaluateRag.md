How to Evaluate RAG

# Agent-Office Project 
- use test case 
  - file + query
    - Recall @5 
      - % of case with relevant docs in top-5
    - MRR
      - mean(1/rank) -> reward higher rank
    - Accuracy
      - Correct cititaion 
    - Consistency 
      - Alternative to LLM as judge 


Consistency
```python
terms = case.get("expected_terms")          # e.g. ["maternity leave", "14 weeks", "FMLA"]
covered = sum(1 for term in terms
              if _normalize(term) in normalized_answer)

consistency = covered / len(terms)          # fraction of expected terms present
```


# from Claude
```python
# What to measure
{
    "context_precision":  "are retrieved chunks actually relevant?",
    "context_recall":     "did we miss important chunks?",
    "chunk_utilization":  "did the LLM actually USE what was retrieved?"
}
```

## Evaluating RAG in Production — Complete Guide

---

### The Core Problem

```
Dev evaluation  → static dataset, you control everything
Production      → real users, unknown queries, no ground truth labels
```

You need **multiple layers** because no single metric captures RAG quality.

---

### Layer 1 — Retrieval Quality

```python
# What to measure
{
    "context_precision":  "are retrieved chunks actually relevant?",
    "context_recall":     "did we miss important chunks?",
    "chunk_utilization":  "did the LLM actually USE what was retrieved?"
}
```

**In production without labels:**

```python
# Cross-encoder reranker score as a proxy for relevance
relevance_score = cross_encoder.predict([(query, chunk) for chunk in hits])

# Low score = retrieval is failing silently
if mean(relevance_score) < THRESHOLD:
    alert("retrieval quality degraded")
```

| Signal | How to get it | Cost |
|--------|--------------|------|
| Reranker confidence scores | From your reranker model | Free |
| Click-through on cited sources | UI instrumentation | Free |
| User "thumbs down" on answers | Feedback widget | Free |
| LLM-as-judge on chunk relevance | Async GPT-4 call | $$$ |

---

### Layer 2 — Generation Quality

**The 3 axes that matter:**

```
Faithfulness  →  does the answer contradict the retrieved context?
Relevance     →  does the answer actually address the question?
Completeness  →  did the answer use ALL relevant info from context?
```

**Practical production setup:**

```python
# Run async, not in the critical path
async def evaluate_generation(query, context_chunks, answer):
    
    # 1. Faithfulness — NLI model (fast, cheap)
    entailment_score = nli_model.predict(
        premise="\n".join(context_chunks),
        hypothesis=answer
    )
    
    # 2. Relevance — embedding similarity (fast, cheap)
    relevance = cosine_similarity(
        embed(query), 
        embed(answer)
    )
    
    # 3. Sample 5% with LLM judge (slow, expensive)
    if random() < 0.05:
        llm_score = await gpt4_judge(query, context_chunks, answer)
    
    return {
        "faithfulness": entailment_score,
        "relevance": relevance,
        "llm_score": llm_score or None
    }
```

---

### Layer 3 — LLM-as-Judge (The Gold Standard)

```python
JUDGE_PROMPT = """
You are evaluating a RAG system response.

Query: {query}
Retrieved Context: {context}
Answer: {answer}

Score each dimension 1-5:
1. FAITHFULNESS: Is every claim in the answer supported by the context?
2. RELEVANCE: Does the answer directly address the query?
3. COMPLETENESS: Does it use all relevant information from context?
4. HALLUCINATION: Are there any facts NOT in the context? (5=none, 1=many)

Return JSON only:
{{"faithfulness": X, "relevance": X, "completeness": X, "hallucination": X, "reasoning": "..."}}
"""

# Run on a sample — not every query
```

**Sampling strategy:**

```
100% of queries    → cheap signals (latency, citation check, NLI)
 10% of queries    → embedding similarity scores  
  5% of queries    → LLM-as-judge
  1% of queries    → human review queue
```

---

### Layer 4 — User Signals (Most Valuable)

```python
# Instrument your UI to capture implicit signals

signals = {
    # Explicit
    "thumbs_up":          +1.0,
    "thumbs_down":        -1.0,
    "copy_to_clipboard":  +0.5,   # user found it useful enough to copy
    
    # Implicit
    "follow_up_query":    -0.3,   # had to ask again = answer incomplete
    "session_abandoned":  -0.5,   # user left immediately
    "cited_source_click": +0.4,   # engaged with retrieval
    "long_dwell_time":    +0.3,   # read the full answer
}

# These are FREE and highly signal-rich
```

---

### Layer 5 — Systematic Failure Detection

```python
# Patterns that indicate systemic failures

class RAGHealthMonitor:
    
    def check_retrieval_drift(self):
        # Embedding model drift — cosine scores dropping over time
        # New document formats not being chunked correctly
        pass
    
    def check_hallucination_spike(self):
        # NLI contradiction scores trending up
        # Citation snippet match rate dropping
        pass
    
    def check_coverage_gaps(self):
        # Queries with 0 relevant chunks retrieved
        # High frequency queries with low satisfaction
        pass
    
    def check_latency_vs_quality(self):
        # Is top_k too low? Are we sacrificing quality for speed?
        pass
```

---

### Production Architecture

```
Request
   │
   ▼
┌─────────────────────────────────────────┐
│           RAG Pipeline                  │
│  Retrieve → Rerank → Generate → Cite    │
└──────────────┬──────────────────────────┘
               │ async, non-blocking
               ▼
┌─────────────────────────────────────────┐
│         Evaluation Sidecar              │
│                                         │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ Fast Checks │  │  Async Checks    │  │
│  │ (< 10ms)    │  │  (seconds)       │  │
│  │             │  │                  │  │
│  │ • cite check│  │ • NLI score      │  │
│  │ • latency   │  │ • embed sim      │  │
│  │ • null check│  │ • LLM judge(5%)  │  │
│  └─────────────┘  └──────────────────┘  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│         Metrics Store                   │
│  (time-series DB — InfluxDB/Prometheus) │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│           Dashboards + Alerts           │
│                                         │
│  • Retrieval quality over time          │
│  • Hallucination rate by dept/topic     │
│  • User satisfaction trend              │
│  • Failure cluster analysis             │
└─────────────────────────────────────────┘
```

---

### What to Alert On

```python
ALERT_RULES = {
    # Immediate alerts
    "citation_match_rate < 0.7":     "CRITICAL - hallucinated citations",
    "null_answer_rate > 0.05":       "CRITICAL - retrieval failing",
    "p95_latency > 8s":              "WARNING  - user experience degraded",
    
    # Trend alerts (over 1hr window)  
    "faithfulness trending down":    "WARNING  - generation quality drift",
    "thumbs_down_rate > 0.15":       "WARNING  - user dissatisfaction spike",
    "retrieval_score drop > 20%":    "WARNING  - embedding/index drift",
}
```

---

### Recommended Tooling

| Tool | Purpose | Cost |
|------|---------|------|
| **RAGAS** | Offline eval framework | Free |
| **LangSmith** | Tracing + online eval | $$ |
| **Arize Phoenix** | Embedding drift detection | Free/$ |
| **Braintrust** | Dataset + eval management | $$ |
| **Custom NLI** | Faithfulness at scale | Free |
| **Prometheus + Grafana** | Metrics dashboards | Free |

---

### The Minimal Viable Setup

If you can only do **3 things**, do these:

```
1. Citation verification    → catches hallucination cheaply, already in your code
2. Thumbs up/down widget    → real user signal, free
3. LLM judge on 5% sample  → catches what rules miss, manageable cost
```

> **Key insight:** Offline eval (like your current code) tells you if RAG *can* work. Production eval tells you if RAG *is* working — for real users, on real queries, right now.