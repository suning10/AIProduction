# Summary of handle conflict 

- Type of conflict 
  - Version
  - Scope
  - True Conflict 
    - Record Conflict when upload 

- Detect conflict before generation 
  - use NLI model 
  - use embedding - semantic 
    - add threshold
- Resolve 
  - **metadata is the key !** 
  - solve by version in metadata 
  - solve by effective data
  - by priority 
    - rank 2 docs by 
      - doc_type (metadata)
- Production
  - use a tier solution 
    - metadata - alwasys run o(1) 
    - embedding ~ 2ms
    - not passed 
      - run NLI


## Handling Conflicting Documents in RAG

---

### What Conflict Looks Like

```
Query: "What is the notice period for resignation?"

Chunk A (HR Policy v1, 2021): "Notice period is 2 weeks"
Chunk B (HR Policy v3, 2024): "Notice period is 4 weeks"  
Chunk C (Employment Contract): "Notice period is 3 months for senior staff"

→ LLM picks one silently, user gets wrong answer with false confidence
```

**Types of conflicts:**

```
┌─────────────────┬────────────────────────────────────────────┐
│ Type            │ Example                                    │
├─────────────────┼────────────────────────────────────────────┤
│ Version conflict│ Old policy vs new policy same topic        │
│ Scope conflict  │ General rule vs exception for a dept/role  │
│ Format conflict │ "2 weeks" vs "14 days" (same thing)        │
│ Partial conflict│ Doc A covers part, Doc B contradicts part  │
│ True conflict   │ Genuine disagreement, no resolution        │
└─────────────────┴────────────────────────────────────────────┘
```

---

### Step 1 — Detect Conflicts Before Generation

```python
class ConflictDetector:
    
    async def detect(self, query: str, chunks: list[Chunk]) -> ConflictReport:
        
        # Method 1 — Fast: NLI contradiction detection
        contradictions = []
        for i, chunk_a in enumerate(chunks):
            for chunk_b in chunks[i+1:]:
                
                score = self.nli_model.predict(
                    premise=chunk_a.content,
                    hypothesis=chunk_b.content
                )
                
                # NLI returns: entailment / neutral / contradiction
                if score.label == "contradiction" and score.confidence > 0.7:
                    contradictions.append(Contradiction(
                        chunk_a=chunk_a,
                        chunk_b=chunk_b,
                        confidence=score.confidence
                    ))
        
        # Method 2 — Semantic: embedding distance on same topic
        # chunks about same topic should be CLOSE in embedding space
        # but if they're close yet contradict = conflict
        for pair in contradictions:
            similarity = cosine_similarity(
                embed(pair.chunk_a.content),
                embed(pair.chunk_b.content)
            )
            pair.is_same_topic = similarity > 0.8  # same topic, contradicts = real conflict
        
        return ConflictReport(
            has_conflicts=len(contradictions) > 0,
            conflicts=contradictions,
            severity=self._severity(contradictions)
        )
    
    def _severity(self, contradictions):
        if not contradictions:
            return "none"
        if any(c.confidence > 0.9 for c in contradictions):
            return "high"
        if any(c.confidence > 0.7 for c in contradictions):
            return "medium"
        return "low"
```

---

### Step 2 — Resolve Automatically Where Possible

#### Strategy A — Version-Based Resolution (Most Common Fix)

```python
class VersionResolver:
    
    def resolve(self, conflicts: list[Contradiction]) -> list[Chunk]:
        resolved = []
        
        for conflict in conflicts:
            winner = self._pick_by_version(
                conflict.chunk_a, 
                conflict.chunk_b
            )
            resolved.append(winner)
        
        return resolved
    
    def _pick_by_version(self, a: Chunk, b: Chunk) -> Chunk:
        
        # Priority order — most specific/recent wins
        priority_rules = [
            self._by_effective_date,     # newer date wins
            self._by_version_number,     # higher version wins
            self._by_document_hierarchy, # contract > policy > guideline
            self._by_dept_specificity,   # dept-specific > general
        ]
        
        for rule in priority_rules:
            result = rule(a, b)
            if result is not None:
                return result
        
        return None  # unresolvable — escalate
    
    def _by_effective_date(self, a, b):
        date_a = a.metadata.get("effective_date")
        date_b = b.metadata.get("effective_date")
        
        if date_a and date_b:
            return a if date_a > date_b else b
        return None
    
    def _by_document_hierarchy(self, a, b):
        # Define your authority hierarchy
        hierarchy = {
            "employment_contract": 5,
            "legal_policy":        4,
            "hr_policy":           3,
            "department_guide":    2,
            "faq":                 1,
        }
        rank_a = hierarchy.get(a.metadata.get("doc_type"), 0)
        rank_b = hierarchy.get(b.metadata.get("doc_type"), 0)
        
        if rank_a != rank_b:
            return a if rank_a > rank_b else b
        return None
    
    def _by_dept_specificity(self, a, b):
        # Dept-specific rule overrides general rule
        a_specific = a.metadata.get("dept") is not None
        b_specific = b.metadata.get("dept") is not None
        
        if a_specific and not b_specific:
            return a
        if b_specific and not a_specific:
            return b
        return None
```

#### Strategy B — Scope-Based Resolution

```python
def resolve_by_scope(query: str, chunks: list[Chunk], user_context: dict) -> list[Chunk]:
    """
    Apply the chunk that matches the user's specific context
    """
    user_dept   = user_context.get("dept")
    user_role   = user_context.get("role")
    user_level  = user_context.get("seniority")
    
    scored = []
    for chunk in chunks:
        scope_match = 0
        
        # Exact dept match = strongest signal
        if chunk.metadata.get("dept") == user_dept:
            scope_match += 3
        
        # Role match
        if user_role in chunk.metadata.get("applicable_roles", []):
            scope_match += 2
        
        # Seniority match
        if user_level in chunk.metadata.get("applicable_levels", []):
            scope_match += 2
        
        # General policy (no scope) = lowest priority
        if not chunk.metadata.get("dept"):
            scope_match += 0
        
        scored.append((chunk, scope_match))
    
    # Return highest scope-matching chunks
    scored.sort(key=lambda x: x[1], reverse=True)
    
    top_score = scored[0][1]
    # Return all chunks at the top scope level
    return [c for c, s in scored if s == top_score]
```

---

### Step 3 — Handle Unresolvable Conflicts in Generation

```python
CONFLICT_AWARE_PROMPT = """
You are answering based on retrieved documents that may conflict.

User Query: {query}

Retrieved Context:
{formatted_chunks}

Instructions:
1. CHECK if any documents contradict each other on the query topic
2. If RESOLVABLE (different dates/versions):
   - Use the most recent/authoritative source
   - Mention the older source is superseded
3. If SCOPE-BASED (different applies to different people):  
   - Explain EACH rule and WHO it applies to
4. If GENUINELY UNRESOLVABLE:
   - State BOTH positions clearly
   - DO NOT pick one silently
   - Tell the user to verify with HR/Legal
5. ALWAYS cite your sources: [Source: filename, Date: date]

NEVER fabricate a resolution. Uncertainty is better than false confidence.
"""

def format_chunks_with_metadata(chunks: list[Chunk]) -> str:
    """Give LLM full context to reason about conflicts"""
    
    formatted = []
    for i, chunk in enumerate(chunks, 1):
        formatted.append(f"""
--- Source {i} ---
File: {chunk.metadata.get('filename')}
Type: {chunk.metadata.get('doc_type')}
Department: {chunk.metadata.get('dept', 'General')}
Effective Date: {chunk.metadata.get('effective_date', 'Unknown')}
Version: {chunk.metadata.get('version', 'Unknown')}
Content: {chunk.content}
""")
    return "\n".join(formatted)
```

---

### Step 4 — Response Patterns for Each Conflict Type

```python
# These are the answer shapes your system should produce

RESPONSE_PATTERNS = {
    
    "version_conflict": """
        The policy was updated. According to the current policy 
        (v3, effective Jan 2024): [CURRENT ANSWER].
        
        Note: An older version (v1, 2021) stated [OLD ANSWER], 
        but this has been superseded.
        
        [Source: HR Policy v3, Jan 2024]
    """,
    
    "scope_conflict": """
        This depends on your role/department:
        
        • General staff: 2 weeks notice [Source: HR Policy]
        • Senior staff (Grade 5+): 3 months notice [Source: Employment Contract Template]
        • Engineering dept: 4 weeks notice [Source: Engineering Dept Policy]
        
        Please confirm which applies to your situation.
    """,
    
    "genuine_conflict": """
        I found conflicting information in our documents and cannot 
        determine the correct answer with confidence:
        
        • [Document A] states: [POSITION A]
        • [Document B] states: [POSITION B]
        
        I recommend contacting HR directly to confirm which applies 
        to your situation. I've flagged this conflict for review.
    """,
    
    "format_conflict": """
        The notice period is 14 days (some documents refer to this 
        as "2 weeks" — these are the same requirement).
        
        [Source: HR Policy v3]
    """
}
```

---

### Step 5 — Escalation & Feedback Loop

```python
class ConflictEscalator:
    
    async def handle(
        self, 
        query: str, 
        conflict: ConflictReport, 
        resolution: Resolution
    ):
        
        # Always log conflicts — they reveal data quality issues
        await self.log_conflict(query, conflict)
        
        if conflict.severity == "high" and resolution.type == "unresolvable":
            
            # 1. Flag documents for human review
            await self.flag_for_review(
                docs=[c.doc_id for c in conflict.conflicts],
                reason="Contradictory content detected",
                query=query,
                priority="high"
            )
            
            # 2. Notify document owners
            await self.notify_owners(
                conflict=conflict,
                message=f"Conflicting documents detected for query: '{query}'"
            )
            
            # 3. Optionally route to human agent
            if self.should_escalate_to_human(conflict):
                return await self.route_to_human_agent(query)
        
        # Track resolution success rate
        await self.metrics.record({
            "conflict_type":       conflict.type,
            "resolution_strategy": resolution.strategy,
            "auto_resolved":       resolution.type != "unresolvable",
            "severity":            conflict.severity,
        })
```

---

### Full Pipeline

```
Query + Context
      │
      ▼
┌─────────────────────────┐
│   Conflict Detector     │  ← NLI model checks all chunk pairs
│   (NLI + embeddings)    │
└────────────┬────────────┘
             │
     ┌───────┴────────┐
     │                │
  No conflict      Conflict detected
     │                │
     ▼                ▼
  Generate      ┌─────────────────────────────┐
  normally      │      Conflict Resolver      │
                │                             │
                │  1. Version resolver        │ → auto-resolve
                │  2. Scope resolver          │ → auto-resolve  
                │  3. Format normalizer       │ → auto-resolve
                │  4. Unresolvable handler    │ → flag + explain
                └─────────────┬───────────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  Conflict-Aware      │
                   │  Prompt + Generate   │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  Escalation Layer    │
                   │  Log + Flag + Notify │
                   └──────────────────────┘
```

---

### Metadata is the Root Fix

```
All automatic resolution depends on having good metadata.

Without metadata          With metadata
──────────────────        ──────────────────────────────
"Policy says 2 weeks"  →  doc_type: "hr_policy"
"Policy says 4 weeks"     effective_date: "2024-01-01"
                          version: "3.0"
         ↓                dept: "general"
  Cannot resolve           ↓
                       Automatically pick v3.0
```

```python
# Minimum metadata every document needs for conflict resolution
REQUIRED_METADATA = {
    "effective_date":    "when this version became active",
    "version":           "document version number",
    "doc_type":          "policy | contract | guideline | faq",
    "dept":              "None if global, dept name if specific",
    "supersedes":        "ID of document this replaces",
    "applicable_roles":  "which roles this applies to",
    "review_date":       "when this should be reviewed/expired",
}
```

---

### Priority Order

```
┌────┬──────────────────────────────────┬──────────────────────────┐
│ #  │ Action                           │ Resolves                 │
├────┼──────────────────────────────────┼──────────────────────────┤
│ 1  │ Add effective_date to all docs   │ 80% of version conflicts │
│ 2  │ Add doc_type hierarchy           │ Authority conflicts       │
│ 3  │ Add dept/role scope metadata     │ Scope conflicts          │
│ 4  │ NLI conflict detection           │ Catches what rules miss  │
│ 5  │ Conflict-aware prompt            │ Transparent to user      │
│ 6  │ Escalation + flagging pipeline   │ Fixes root cause in data │
└────┴──────────────────────────────────┴──────────────────────────┘
```

> **Core principle:** Conflicts are a **data governance problem** disguised as an AI problem. The real fix is upstream — clean versioning, clear document ownership, and mandatory metadata. The RAG layer should detect and surface conflicts, not silently pick one.