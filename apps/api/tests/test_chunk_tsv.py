"""G3 入库时 tsv 生成逻辑测试（源码断言，因 SQLite 跑不了 to_tsvector）。"""


def test_archiver_generates_tsv_on_ingest():
    """归档流入库时 chunk 应生成 tsv（仅 PG，用 is_postgres 守卫）。"""
    import inspect
    from app.rag import archiver
    src = inspect.getsource(archiver.archive_project)
    assert 'to_tsvector' in src or "tsv = to_tsvector" in src, "archiver 缺少 tsv 生成"
    assert 'is_postgres' in src, "archiver 缺少 is_postgres 守卫"


def test_ingest_chunks_generates_tsv():
    """导入流入库时 chunk 应生成 tsv（_write_chunks_unembedded，异步化后改名）。"""
    import inspect
    from app.services import knowledge_service
    src = inspect.getsource(knowledge_service._write_chunks_unembedded)
    assert 'to_tsvector' in src or "tsv = to_tsvector" in src, "_write_chunks_unembedded 缺少 tsv 生成"
    assert 'is_postgres' in src, "_write_chunks_unembedded 缺少 is_postgres 守卫"


def test_archiver_tsv_filter_by_source_id():
    """archiver 的 tsv 回填应按 source_id 过滤（避免误改其他项目的 chunk）。"""
    import inspect
    from app.rag import archiver
    src = inspect.getsource(archiver.archive_project)
    assert 'source_id = :sid' in src or "source_id = :sid" in src, "archiver tsv 回填缺 source_id 过滤"


def test_ingest_chunks_tsv_filter_by_file_id():
    """_write_chunks_unembedded 的 tsv 回填应按 file_id 过滤。"""
    import inspect
    from app.services import knowledge_service
    src = inspect.getsource(knowledge_service._write_chunks_unembedded)
    assert 'file_id = :fid' in src or "file_id = :fid" in src, "_write_chunks_unembedded tsv 回填缺 file_id 过滤"
