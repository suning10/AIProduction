# mitigate poor RAG performance 


- Identify the issue 
  - Retrieval
    - check MRR. top 5
  - Generation
    - check covered vs source
  - Poor doc quality
- Mitigate 
  - Retrieval 
    - chunking strategy 
      - change to semantic chunking 
        - semantic_text_splitter 
    - embedding model 
      - retrain 
      - choose another one
    - glossary 
      - use dict to rewrite
      - use a smaller model to expand query 
  - Generation 
    - lose context 
    - too much chunk goes into prompt 
      - use threshold 
    - prompt engineering
      - add citation 
      - define conflict 
      - never guess 
      - chain of thought
        - list chunks
        - identify gaps
        - construct using relevant 



## Mitigating Low RAG Performance — Complete Playbook

---

### Step 0 — Diagnose First

```
Low performance is not one problem — it's one of three problems:

┌─────────────────────────────────────────────────────┐
│                                                     │
│  1. RETRIEVAL FAILS  →  right answer not retrieved  │
│  2. GENERATION FAILS →  right chunks, wrong answer  │
│  3. DATA FAILS       →  garbage in, garbage out     │
│                                                     │
└─────────────────────────────────────────────────────┘

Fix the right layer or you waste effort.
```

**Quick diagnostic:**

```python
async def diagnose(case):
    hits = await retrieve(case["query"])
    
    relevant_retrieved = any(
        f in case["relevant_files"] 
        for f in [source_file(h) for h in hits]
    )
    
    if not relevant_retrieved:
        return "RETRIEVAL_FAILURE"   # fix retrieval
    
    answer = await generate(case["query"], hits)
    terms_covered = check_terms(answer, case["expected_terms"])
    
    if terms_covered < 0.5:
        return "GENERATION_FAILURE"  # fix prompting/reranking
    
    return "PASS"
```

---

### Problem 1 — Retrieval Failures

#### 1A — Chunking Strategy is Wrong

```
Most common root cause. Bad chunks = bad retrieval, no matter how good your embeddings.
```

```python
# ❌ Bad — fixed size destroys semantic units
chunk_size = 512  # cuts through sentences, tables, lists

# ✅ Better — semantic chunking
from semantic_text_splitter import TextSplitter

splitter = TextSplitter(
    chunk_size=512,
    chunk_overlap=64,          # overlap preserves context at boundaries
    split_on=["paragraph",     # respect document structure
              "sentence"]
)

# ✅ Even better — document-aware chunking
def chunk_document(doc):
    if doc["type"] == "policy":
        return chunk_by_section(doc)      # H1/H2/H3 boundaries
    elif doc["type"] == "table":
        return chunk_by_row_group(doc)    # keep table rows together
    elif doc["type"] == "faq":
        return chunk_by_qa_pair(doc)      # Q+A always stay together
```

#### 1B — Embedding Model Mismatch

```python
# ❌ Generic model on domain-specific content
model = "text-embedding-ada-002"   # trained on web text
# Struggles with: legal terms, medical jargon, internal acronyms

# ✅ Use domain-appropriate model
models = {
    "general":  "text-embedding-3-large",
    "legal":    "legal-bert-base-uncased",
    "medical":  "PubMedBERT",
    "code":     "code-search-net",
    "internal": "fine-tuned on your own corpus"  # best option
}

# ✅ Fine-tune on your query-document pairs
# Even 500 examples dramatically improves domain recall
from sentence_transformers import SentenceTransformer, losses

model = SentenceTransformer("BAAI/bge-base-en-v1.5")
train_examples = load_your_query_doc_pairs()  # hard negatives matter
model.fit(train_objectives=[(train_dataloader, losses.MultipleNegativesRankingLoss(model))])
```

#### 1C — Query-Document Vocabulary Gap

```python
# Problem: user says "time off" but doc says "annual leave entitlement"

# Solution 1 — HyDE (Hypothetical Document Embeddings)
async def hyde_retrieve(query, top_k):
    # Generate a fake answer that LOOKS like a document
    hypothetical_doc = await llm.generate(
        f"Write a short policy excerpt that answers: {query}"
    )
    # Embed the fake doc instead of the query — bridges vocabulary gap
    return await vector_search(hypothetical_doc, top_k)

# Solution 2 — Query expansion
async def expand_query(query):
    expanded = await llm.generate(f"""
        Generate 3 alternative phrasings of this question 
        using different terminology:
        Query: {query}
        Return JSON: {{"alternatives": ["...", "...", "..."]}}
    """)
    return [query] + expanded["alternatives"]

# Solution 3 — Hybrid search (BM25 + vectors)
async def hybrid_retrieve(query, top_k):
    vector_hits = await vector_search(query, top_k * 2)
    keyword_hits = await bm25_search(query, top_k * 2)   # exact term match
    
    # RRF fusion — combines both rankings
    return reciprocal_rank_fusion(vector_hits, keyword_hits, top_k)
```

#### 1D — Add a Reranker

```python
# Vector search finds candidates — reranker finds the RIGHT ones
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

async def retrieve_and_rerank(query, top_k):
    # Retrieve 3x candidates
    candidates = await vector_search(query, top_k=top_k * 3)
    
    # Rerank with cross-encoder (reads query+chunk together)
    scores = reranker.predict([(query, c.content) for c in candidates])
    
    ranked = sorted(zip(candidates, scores), 
                   key=lambda x: x[1], reverse=True)
    
    return [chunk for chunk, score in ranked[:top_k]]
    # Typically improves MRR by 15-30%
```

---

### Problem 2 — Generation Failures

#### 2A — Context Window Stuffing

```python
# ❌ Bad — dump everything in, model gets confused
prompt = f"Context: {all_chunks_concatenated}\nQuestion: {query}"

# ✅ Better — curate what goes in
async def build_context(query, hits, max_tokens=3000):
    
    # 1. Deduplicate near-identical chunks
    hits = deduplicate(hits, threshold=0.92)
    
    # 2. Score each chunk for actual relevance to query
    scores = reranker.predict([(query, h.content) for h in hits])
    
    # 3. Only include chunks above relevance threshold
    relevant = [h for h, s in zip(hits, scores) if s > 0.4]
    
    # 4. Fit within token budget, best chunks first
    context = []
    tokens_used = 0
    for chunk in relevant:
        chunk_tokens = count_tokens(chunk.content)
        if tokens_used + chunk_tokens < max_tokens:
            context.append(chunk)
            tokens_used += chunk_tokens
    
    return context
```

#### 2B — Prompt Engineering

```python
# ❌ Weak prompt
prompt = f"Context: {context}\nAnswer: {query}"

# ✅ Strong prompt with explicit instructions
SYSTEM_PROMPT = """
You are a precise assistant that answers ONLY from provided context.

Rules:
1. If the context does not contain the answer, say "I don't have 
   information about this" — never guess
2. Cite the specific section you used: [Doc: filename, Section: X]
3. If multiple chunks conflict, state the conflict explicitly
4. Use the same terminology as the source documents
5. Answer in {language} at {reading_level} reading level
"""

# ✅ Chain-of-thought for complex queries
COT_PROMPT = """
Before answering:
1. List which provided chunks are relevant to the question
2. Identify any gaps in the provided context  
3. Then construct your answer using only relevant chunks

Question: {query}
Context: {context}
"""
```

#### 2C — Answer Validation Loop

```python
async def generate_with_validation(query, chunks, max_retries=2):
    
    for attempt in range(max_retries):
        answer = await llm.generate(query, chunks)
        
        # Check 1 — did it hallucinate citations?
        if not all_citations_valid(answer.citations, chunks):
            chunks = filter_to_cited_chunks(chunks)  # retry with less context
            continue
        
        # Check 2 — NLI faithfulness check
        faithfulness = nli_model.predict(
            premise="\n".join(c.content for c in chunks),
            hypothesis=answer.content
        )
        if faithfulness < 0.7:
            query = f"{query}\nIMPORTANT: Only use information explicitly stated in the context."
            continue
        
        # Check 3 — did it actually answer the question?
        relevance = cosine_similarity(embed(query), embed(answer.content))
        if relevance < 0.6:
            query = f"Answer this specific question directly: {query}"
            continue
            
        return answer
    
    return fallback_answer("Could not generate a reliable answer")
```

---

### Problem 3 — Data Quality Failures

#### 3A — Document Ingestion Pipeline

```python
class DocumentQualityGate:
    
    async def process(self, raw_doc):
        
        # 1. Extract properly (biggest hidden failure)
        if raw_doc.type == "pdf":
            # ❌ PyPDF2 — loses tables, columns, formatting
            # ✅ Use proper PDF parser
            text = await pymupdf_extract(raw_doc)      # better layout
            # ✅ Or for scanned PDFs
            text = await ocr_pipeline(raw_doc)         # Tesseract/AWS Textract
        
        # 2. Quality filters before indexing
        checks = {
            "too_short":    len(text) < 100,
            "garbled_ocr":  garbled_ratio(text) > 0.2,   # ���û§ type chars
            "boilerplate":  is_footer_header_only(text),
            "duplicate":    await self.is_near_duplicate(text),
        }
        
        if any(checks.values()):
            await self.quarantine(raw_doc, reason=checks)
            return None
        
        # 3. Enrich metadata (critical for filtering)
        doc.metadata = {
            "dept":        extract_department(text),
            "doc_type":    classify_doc_type(text),    # policy/faq/form
            "effective_date": extract_date(text),
            "version":     extract_version(text),
            "topics":      extract_topics(text),       # for filtering
        }
        
        return doc
```

#### 3B — Keep Index Fresh

```python
# Stale documents are silent killers — answer is retrieved but outdated

class IndexFreshness:
    
    async def audit(self):
        stale = []
        for doc in await store.list_documents():
            
            # Check if source has been updated
            source_modified = await source_system.last_modified(doc.source_id)
            if source_modified > doc.indexed_at:
                stale.append(doc)
            
            # Flag very old documents for human review
            age_days = (now() - doc.effective_date).days
            if age_days > 365:
                await flag_for_review(doc)
        
        return stale
    
    async def reindex_stale(self, stale_docs):
        for doc in stale_docs:
            await store.delete_chunks(doc.id)      # remove old chunks
            await ingest_pipeline.process(doc)     # reindex fresh
```

---

### Advanced Strategies

#### Multi-Index Architecture

```
┌─────────────────────────────────────────────────┐
│                  Query Router                   │
│                                                 │
│   "what is maternity leave?"  →  Policy Index  │
│   "how do I submit expenses?" →  Process Index │
│   "John's contract terms"     →  HR Data Index │
└────────────────────┬────────────────────────────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
    Policy Index  Process    HR Data
    (semantic)    Index      Index
                  (keyword)  (structured)
```

```python
async def route_and_retrieve(query):
    route = await classifier.classify(query)  # fast, cheap model
    
    strategies = {
        "policy":    lambda q: hybrid_search(q, index="policies"),
        "process":   lambda q: bm25_search(q, index="processes"),
        "personal":  lambda q: structured_query(q, index="hr_data"),
        "general":   lambda q: multi_index_search(q),
    }
    
    return await strategies[route](query)
```

#### Contextual Compression

```python
async def compress_chunks(query, chunks):
    """Extract only the relevant sentences from each chunk"""
    
    compressed = []
    for chunk in chunks:
        # Ask LLM to extract only the relevant part
        relevant_excerpt = await llm.generate(f"""
            From the following text, extract ONLY the sentences 
            relevant to: "{query}"
            If nothing is relevant, return empty string.
            
            Text: {chunk.content}
        """)
        
        if relevant_excerpt.strip():
            compressed.append(ChunkResult(
                content=relevant_excerpt,
                source=chunk.source,       # keep attribution
                doc_id=chunk.doc_id
            ))
    
    # Now context window has signal, not noise
    return compressed
```

---

### Mitigation Decision Tree

```
Low metric detected
        │
        ├── Low MRR / Recall@5
        │         │
        │         ├── Check chunk sizes        → resize + overlap
        │         ├── Check embedding model    → upgrade or fine-tune  
        │         ├── Check vocabulary gap     → add HyDE or expansion
        │         └── Check metadata filters  → filters too aggressive?
        │
        ├── Low Citation Correctness
        │         │
        │         ├── Check prompt strictness  → add citation rules
        │         ├── Check chunk coherence    → chunks split mid-fact?
        │         └── Add validation loop      → retry on bad citations
        │
        ├── Low Answer Consistency
        │         │
        │         ├── Check context quality    → add reranker
        │         ├── Check prompt completeness → add CoT prompting
        │         └── Check doc coverage       → missing source docs?
        │
        └── All metrics low
                  │
                  └── Data quality audit first → garbage in, garbage out
```

---

### Priority Order

```
┌────┬──────────────────────────────┬──────────┬────────────┐
│ #  │ Action                       │ Effort   │ Impact     │
├────┼──────────────────────────────┼──────────┼────────────┤
│ 1  │ Fix chunking strategy        │ Medium   │ Very High  │
│ 2  │ Add hybrid search (BM25+vec) │ Low      │ High       │
│ 3  │ Add cross-encoder reranker   │ Low      │ High       │
│ 4  │ Improve prompt strictness    │ Very Low │ Medium     │
│ 5  │ Audit data quality           │ High     │ Very High  │
│ 6  │ Add query expansion/HyDE     │ Medium   │ Medium     │
│ 7  │ Fine-tune embedding model    │ High     │ Very High  │
│ 8  │ Add validation/retry loop    │ Medium   │ Medium     │
└────┴──────────────────────────────┴──────────┴────────────┘

Start with 1, 2, 3 — highest ROI, lowest effort.
```

> **Key principle:** Measure before and after each change in isolation. Multiple simultaneous changes make it impossible to know what actually helped.
