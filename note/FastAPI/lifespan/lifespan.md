# Lifespan
- why use 
  - before app start (**before yield**) 
    - pre-warm the application
      - start db connection, set up data, etc.
  - before app end
    - close db connection 
- How 
  - @asynccontextmanager
    async def lifespan(app: FastAPI):

example
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    container = build_container(settings)
    app.state.container = container

    # 连接外部依赖（memory 模式跳过）
    if container.mongo is not None:
        try:
            await container.mongo.connect()
        except Exception as exc:  # noqa: BLE001
            logger.error("MongoDB 连接失败: %s", exc)
    if hasattr(container.session_store, "connect"):
        try:
            await container.session_store.connect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 连接失败(%s)，会话回退内存", exc)

    # 种子默认 Rules / Hooks
    await container.rule_engine.seed_defaults()
    await container.hook_engine.seed_defaults()
    seeded_skills = await seed_default_skills(container.store)
    if seeded_skills:
        logger.info("已创建 %d 个可执行基线 Skills", seeded_skills)

    # 种子账号（学生/管理员）
    await container.auth.seed_users()

    # 回填部门 Loop 阶段与审核统计字段（兼容旧数据）
    await _backfill_departments(container)

    # 重建内存检索索引（BM25 + 向量）：MongoDB 中已入库的文档可跨进程/重启被检索
    try:
        chunks = await container.store.list_active_chunks()
        if chunks:
            for c in chunks:
                container.bm25.add(c)
            # 共享 Mongo 向量库已持久化，无需每个 Pod 启动时重复嵌入全量文档。
            if settings.vector_backend != "mongo":
                texts = [c["content"] for c in chunks]
                vectors = await container.embeddings.embed(texts)
                for c, v in zip(chunks, vectors):
                    await container.vector_store.add(
                        c["embedding_id"],
                        v,
                        {"doc_id": c["doc_id"], "dept_id": c["dept_id"], "chunk_index": c["chunk_index"]},
                    )
            logger.info("重建检索索引完成: %d chunks (BM25 + 向量)", len(chunks))
        else:
            logger.info("无已入库文档，跳过检索索引重建")
    except Exception as exc:  # noqa: BLE001
        logger.warning("重建检索索引失败(%s)，检索可能不完整", exc)

    logger.info("%s 启动完成 (storage=%s)", settings.app_name, settings.storage_mode)
    yield

    # 关闭
    if container.mongo is not None:
        await container.mongo.close()
    if hasattr(container.session_store, "close"):
        await container.session_store.close()
    await container.pi_runtime.close()
    logger.info("应用已关闭")
```