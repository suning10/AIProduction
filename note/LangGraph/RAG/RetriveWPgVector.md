# how to use pgvector to retrieve content
1. embed query 
2. define comparator 
3. use it in SQL 

```python

        # 2. embed the query
        query_embedding = await self._embed_query(query)
        # 3. calculate cosine_distance by ini a pgvector comparator
        distance = col(DocumentChunk.embedding).cosine_distance(query_embedding)
        # 4 run sql to retrieve top k
        # 4.1 join Document to make sure user have access of the file 
        # 4.2 achieve this by looking at document.group_id is in accessible_group_ids
        with Session(self.engine) as session:
            statement = (
                select(DocumentChunk, Document, distance.label("distance"))
                .join(Document, col(DocumentChunk.document_id) == col(Document.id))
                .where(col(Document.group_id).in_(accessible_group_ids))
                .where(distance <= settings.RAG_MAX_DISTANCE)
                .order_by(distance)
                .limit(top_k or settings.RAG_TOP_K)
            )
            rows = session.exec(statement).all()
```