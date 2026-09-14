# Summary

## How to Control User Access When RAG

### Add metadata to document 
```python
document = {
    "content": "Confidential Q4 financials...",
    "embedding": [...],
    "metadata": {
        "doc_id": "fin-001",
        "owner": "alice@company.com",
        "roles": ["finance", "executives"],
        "department": "finance",
        "classification": "confidential"
    }
}
```
- Pre-Retrival (most common)
  - filter based on rols / owner / classification 
- Post-Retrival
  - best-practice, do a post-retrival check after pre-retrival
- Namespace/isolation
  - add namespace to each DB
- Refresh ACL every x minutes



# Access Control in RAG Systems

## Core Challenge

RAG must ensure users only retrieve/see documents they're **authorized to access** — not just authenticate them at the UI level.

---

## Access Control Strategies

### 1. Pre-Retrieval Filtering (Most Common)
Filter documents **before** vector search using metadata

```python
# Store permissions as metadata during indexing
document = {
    "content": "Confidential Q4 financials...",
    "embedding": [...],
    "metadata": {
        "doc_id": "fin-001",
        "owner": "alice@company.com",
        "roles": ["finance", "executives"],
        "department": "finance",
        "classification": "confidential"
    }
}

# At query time - apply user's permissions as filter
def retrieve_with_acl(query, user_context):
    user_roles = user_context["roles"]  # ["finance"]
    user_id = user_context["user_id"]
    
    # Filter BEFORE vector search
    filters = {
        "$or": [
            {"roles": {"$in": user_roles}},
            {"owner": user_id},
            {"classification": "public"}
        ]
    }
    
    results = vector_db.query(
        query_embedding=embed(query),
        filter=filters,
        top_k=5
    )
    return results
```

---

### 2. Post-Retrieval Filtering
Filter results **after** retrieval (less efficient but sometimes necessary)

```python
def retrieve_and_filter(query, user_context):
    # Retrieve broadly
    raw_results = vector_db.query(
        query_embedding=embed(query),
        top_k=20  # Get more to compensate for filtering
    )
    
    # Filter based on permissions
    authorized_results = [
        doc for doc in raw_results
        if user_has_access(user_context, doc)
    ]
    
    return authorized_results[:5]  # Return top 5 authorized

def user_has_access(user, doc):
    # Check document ACL
    doc_acl = get_acl(doc["doc_id"])
    return (
        user["id"] in doc_acl["allowed_users"] or
        any(role in doc_acl["allowed_roles"] for role in user["roles"]) or
        doc_acl["is_public"]
    )
```

---

### 3. Namespace / Index Segregation
Separate vector stores per user group (strong isolation)

```python
class SegregatedRAG:
    def __init__(self):
        self.indexes = {
            "public":      VectorDB(namespace="public"),
            "internal":    VectorDB(namespace="internal"),
            "confidential": VectorDB(namespace="confidential"),
            "restricted":  VectorDB(namespace="restricted")
        }
    
    def get_accessible_indexes(self, user):
        clearance = user["clearance_level"]
        mapping = {
            "restricted":   ["public", "internal", "confidential", "restricted"],
            "confidential": ["public", "internal", "confidential"],
            "internal":     ["public", "internal"],
            "public":       ["public"]
        }
        return mapping.get(clearance, ["public"])
    
    def query(self, query_text, user):
        accessible = self.get_accessible_indexes(user)
        all_results = []
        
        for idx_name in accessible:
            results = self.indexes[idx_name].query(
                embed(query_text), top_k=3
            )
            all_results.extend(results)
        
        # Re-rank combined results
        return rerank(all_results, query_text)[:5]
```

---

### 4. Row-Level Security with Vector DBs

```python
# Pinecone example with metadata filtering
results = pinecone_index.query(
    vector=query_embedding,
    top_k=5,
    filter={
        "allowed_users": {"$in": [current_user_id]},
        # OR
        "allowed_groups": {"$in": user_groups},
    },
    include_metadata=True
)

# Weaviate example
results = weaviate_client.query\
    .get("Document", ["content", "title"])\
    .with_near_vector({"vector": query_embedding})\
    .with_where({
        "operator": "Or",
        "operands": [
            {"path": ["allowedRoles"], "operator": "ContainsAny", 
             "valueStringArray": user_roles},
            {"path": ["isPublic"], "operator": "Equal", 
             "valueBoolean": True}
        ]
    })\
    .with_limit(5)\
    .do()
```

---

## Full Architecture

```
┌─────────────┐
│    User     │
└──────┬──────┘
       │ Request + JWT/Token
       ▼
┌─────────────────┐
│  Auth Layer     │  ← Validate identity, extract roles/permissions
│  (OAuth/OIDC)   │
└──────┬──────────┘
       │ User Context {id, roles, clearance, groups}
       ▼
┌─────────────────┐
│  RAG Middleware │  ← Build ACL filters from user context
│  (ACL Builder)  │
└──────┬──────────┘
       │ Query + Filters
       ▼
┌─────────────────┐     ┌──────────────────┐
│  Vector DB      │────▶│  Document Store  │
│  (w/ metadata   │     │  (source of truth│
│   filtering)    │     │   for ACLs)      │
└──────┬──────────┘     └──────────────────┘
       │ Authorized chunks only
       ▼
┌─────────────────┐
│   LLM           │  ← Only sees authorized context
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  Response +     │  ← Optionally cite sources with access level
│  Source Citations│
└─────────────────┘
```

---

## Document Ingestion with ACL

```python
class RAGIngestionPipeline:
    def ingest_document(self, doc_path, acl_config):
        # 1. Extract content
        content = extract_text(doc_path)
        
        # 2. Chunk content
        chunks = chunk_text(content, chunk_size=512)
        
        # 3. Get ACL from source system (SharePoint, S3, etc.)
        acl = self.fetch_acl_from_source(doc_path, acl_config)
        
        # 4. Embed and store with ACL metadata
        for i, chunk in enumerate(chunks):
            embedding = embed(chunk)
            
            self.vector_db.upsert({
                "id": f"{doc_id}_{i}",
                "values": embedding,
                "metadata": {
                    "content": chunk,
                    "doc_id": doc_id,
                    "source": doc_path,
                    # ACL fields
                    "allowed_users": acl["users"],
                    "allowed_groups": acl["groups"],
                    "allowed_roles": acl["roles"],
                    "classification": acl["classification"],
                    "is_public": acl["is_public"],
                    # Audit fields
                    "last_acl_sync": datetime.utcnow().isoformat()
                }
            })
    
    def fetch_acl_from_source(self, path, config):
        # Sync from SharePoint, S3 bucket policies, 
        # file system ACLs, database permissions, etc.
        return source_system.get_permissions(path)
```

---

## ACL Sync (Keeping Permissions Fresh)

```python
import schedule

class ACLSyncJob:
    def sync_document_acls(self):
        """Periodically sync ACLs from source systems"""
        
        all_docs = self.vector_db.list_all_documents()
        
        for doc in all_docs:
            current_acl = self.source_system.get_permissions(doc["source"])
            stored_acl = doc["metadata"]["allowed_groups"]
            
            if current_acl != stored_acl:
                # Update metadata in vector DB
                self.vector_db.update_metadata(
                    doc_id=doc["id"],
                    metadata={"allowed_groups": current_acl["groups"],
                              "allowed_users": current_acl["users"],
                              "last_acl_sync": datetime.utcnow().isoformat()}
                )
                
                self.audit_log.record("acl_updated", doc["id"])

# Run every 15 minutes
schedule.every(15).minutes.do(acl_sync_job.sync_document_acls)
```

---

## Preventing Prompt Injection / Data Leakage

```python
def build_secure_prompt(query, retrieved_docs, user_context):
    # Add system-level guardrails
    system_prompt = f"""
    You are an assistant. Answer ONLY based on the provided context.
    - Do NOT reveal information beyond what is in the context
    - Do NOT mention that certain information exists but is restricted
    - User clearance level: {user_context['clearance']}
    - If asked about restricted topics, say: "I don't have information on that"
    """
    
    context = "\n\n".join([
        f"[Source: {doc['source']} | Classification: {doc['classification']}]\n{doc['content']}"
        for doc in retrieved_docs
    ])
    
    return {
        "system": system_prompt,
        "user": f"Context:\n{context}\n\nQuestion: {query}"
    }
```

---

## Best Practices Summary

| Practice | Description |
|----------|-------------|
| **Pre-filter** | Apply ACL filters before vector search (performance + security) |
| **Sync ACLs** | Keep permissions in sync with source systems |
| **Least privilege** | Default to no access, grant explicitly |
| **Audit logging** | Log every retrieval with user + docs accessed |
| **No leakage** | LLM shouldn't hint that restricted docs exist |
| **Token validation** | Always validate JWT/tokens server-side |
| **Namespace isolation** | Use separate indexes for high-security data |
| **Test ACLs** | Regularly test that users can't access unauthorized data |

---

## Tools & Platforms with Native ACL Support

| Tool | ACL Support |
|------|-------------|
| **Pinecone** | Metadata filtering |
| **Weaviate** | RBAC + row-level |
| **Qdrant** | Payload filtering |
| **Elasticsearch** | Document-level security |
| **Azure AI Search** | Security trimming |
| **LangChain** | Custom retrievers with filters |
| **LlamaIndex** | Node postprocessors + filters |

The most robust approach combines **pre-retrieval metadata filtering + periodic ACL sync from source systems + audit logging**.