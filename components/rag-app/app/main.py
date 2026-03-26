import time
import logging
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from .config import settings
from .models import (
    AskRequest, AskResponse, SourceInfo, IngestResponse,
    DocumentInfo, HealthResponse, StatusResponse,
)
from .pipeline import ingestion, chunker, embedder, retriever, generator, audit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RAG Pipeline", version="1.0")

SAMPLE_DOCS_DIR = Path(__file__).parent / "sample_docs"


@app.get("/health", response_model=HealthResponse)
async def health():
    minio_ok = False
    qdrant_ok = False
    models_ok = False
    try:
        client = ingestion.get_s3_client()
        client.list_buckets()
        minio_ok = True
    except Exception:
        pass
    try:
        qclient = retriever.get_qdrant_client()
        qclient.get_collections()
        qdrant_ok = True
    except Exception:
        pass
    try:
        import httpx
        resp = httpx.get(f"{settings.OLLAMA_ENDPOINT}/api/tags", timeout=5.0)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            models_ok = (
                any(settings.EMBEDDING_MODEL in m for m in models) and
                any(settings.CHAT_MODEL in m for m in models)
            )
    except Exception:
        pass
    return HealthResponse(
        status="ok" if (minio_ok and qdrant_ok) else "degraded",
        minio_connected=minio_ok,
        qdrant_connected=qdrant_ok,
        models_loaded=models_ok,
    )


@app.get("/status", response_model=StatusResponse)
async def status():
    try:
        qclient = retriever.get_qdrant_client()
        info = retriever.get_collection_info(qclient)
        chunks = info.get("points_count", 0)
    except Exception:
        chunks = 0

    docs_count = 0
    try:
        s3 = ingestion.get_s3_client()
        keys = ingestion.list_objects(s3, settings.DOCUMENTS_BUCKET)
        docs_count = len(keys)
    except Exception:
        pass

    return StatusResponse(
        documents_ingested=docs_count,
        chunks_stored=chunks,
        embedding_model=settings.EMBEDDING_MODEL,
        chat_model=settings.CHAT_MODEL,
    )


@app.post("/ingest/upload", response_model=IngestResponse)
async def ingest_upload(file: UploadFile = File(...)):
    from fastapi import HTTPException
    try:
        data = await file.read()
        filename = file.filename or "uploaded_file"

        s3 = ingestion.get_s3_client()
        ingestion.ensure_bucket(s3, settings.DOCUMENTS_BUCKET)
        ingestion.upload_object(s3, settings.DOCUMENTS_BUCKET, filename, data)

        text = ingestion.extract_text(filename, data)
        if not text.strip():
            return IngestResponse(files_processed=1, chunks_created=0, message="No text extracted")

        chunks = chunker.chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        chunks_with_vectors = await embedder.embed_chunks(chunks)

        qclient = retriever.get_qdrant_client()
        retriever.store_vectors(qclient, chunks_with_vectors, filename)

        return IngestResponse(
            files_processed=1,
            chunks_created=len(chunks_with_vectors),
            message=f"Ingested {filename}: {len(chunks_with_vectors)} chunks",
        )
    except Exception as e:
        logger.error(f"Ingest upload failed: {e}")
        raise HTTPException(status_code=503, detail=f"Ingestion failed: {e}")


@app.post("/ingest/sample", response_model=IngestResponse)
async def ingest_sample():
    if not SAMPLE_DOCS_DIR.exists():
        return IngestResponse(files_processed=0, chunks_created=0, message="Sample docs not found")

    s3 = ingestion.get_s3_client()
    ingestion.ensure_bucket(s3, settings.DOCUMENTS_BUCKET)

    total_chunks = 0
    files_processed = 0

    for doc_path in sorted(SAMPLE_DOCS_DIR.glob("*")):
        if not doc_path.is_file():
            continue
        data = doc_path.read_bytes()
        filename = doc_path.name

        ingestion.upload_object(s3, settings.DOCUMENTS_BUCKET, filename, data)

        text = ingestion.extract_text(filename, data)
        if not text.strip():
            continue

        chunks = chunker.chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        chunks_with_vectors = await embedder.embed_chunks(chunks)

        qclient = retriever.get_qdrant_client()
        retriever.store_vectors(qclient, chunks_with_vectors, filename)

        total_chunks += len(chunks_with_vectors)
        files_processed += 1

    return IngestResponse(
        files_processed=files_processed,
        chunks_created=total_chunks,
        message=f"Ingested {files_processed} sample documents with {total_chunks} chunks",
    )


@app.post("/ingest/bucket", response_model=IngestResponse)
async def ingest_bucket():
    s3 = ingestion.get_s3_client()
    keys = ingestion.list_objects(s3, settings.DOCUMENTS_BUCKET)

    total_chunks = 0
    files_processed = 0

    for key in keys:
        data = ingestion.download_object(s3, settings.DOCUMENTS_BUCKET, key)
        text = ingestion.extract_text(key, data)
        if not text.strip():
            continue

        chunks = chunker.chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        chunks_with_vectors = await embedder.embed_chunks(chunks)

        qclient = retriever.get_qdrant_client()
        retriever.store_vectors(qclient, chunks_with_vectors, key)

        total_chunks += len(chunks_with_vectors)
        files_processed += 1

    return IngestResponse(
        files_processed=files_processed,
        chunks_created=total_chunks,
        message=f"Ingested {files_processed} files from bucket with {total_chunks} chunks",
    )


@app.get("/documents", response_model=list[DocumentInfo])
async def list_documents():
    try:
        s3 = ingestion.get_s3_client()
        keys = ingestion.list_objects(s3, settings.DOCUMENTS_BUCKET)
    except Exception:
        return []

    qclient = retriever.get_qdrant_client()
    docs = []
    for key in keys:
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            results = qclient.scroll(
                collection_name=retriever.COLLECTION_NAME,
                scroll_filter=Filter(must=[FieldCondition(key="filename", match=MatchValue(value=key))]),
                limit=1,
                with_payload=True,
            )
            points = results[0] if results else []
            chunk_count = len(points) if points else 0
            ingested_at = ""
            if points:
                ingested_at = points[0].payload.get("ingested_at", "")
            # Get actual count by counting all matches
            count_results = qclient.count(
                collection_name=retriever.COLLECTION_NAME,
                count_filter=Filter(must=[FieldCondition(key="filename", match=MatchValue(value=key))]),
            )
            chunk_count = count_results.count
        except Exception:
            chunk_count = 0
            ingested_at = ""
        docs.append(DocumentInfo(filename=key, chunks=chunk_count, ingested_at=ingested_at))
    return docs


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    from fastapi import HTTPException
    start = time.time()
    try:
        query_vector = await embedder.embed_text(req.question)

        qclient = retriever.get_qdrant_client()
        search_results = retriever.search(qclient, query_vector, top_k=req.top_k)

        if not search_results:
            latency = int((time.time() - start) * 1000)
            return AskResponse(
                answer="No relevant documents found. Please ingest some documents first.",
                sources=[],
                latency_ms=latency,
            )

        gen_result = await generator.generate_answer(req.question, search_results)

        latency = int((time.time() - start) * 1000)

        sources = [
            SourceInfo(filename=r["filename"], text=r["text"][:200], score=r["score"])
            for r in search_results
        ]

        audit.log_query(req.question, gen_result["answer"], search_results, latency)

        return AskResponse(
            answer=gen_result["answer"],
            sources=sources,
            latency_ms=latency,
            tokens=gen_result.get("tokens", 0),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ask failed: {e}")
        raise HTTPException(status_code=503, detail=f"Query failed: {e}")


@app.get("/history")
async def query_history():
    try:
        s3 = ingestion.get_s3_client()
        keys = ingestion.list_objects(s3, settings.AUDIT_BUCKET)
        keys.sort(reverse=True)
        keys = keys[:50]

        records = []
        for key in keys:
            data = ingestion.download_object(s3, settings.AUDIT_BUCKET, key)
            import json
            records.append(json.loads(data))
        return {"history": records}
    except Exception:
        return {"history": []}


@app.delete("/collection")
async def delete_collection():
    qclient = retriever.get_qdrant_client()
    retriever.delete_collection(qclient)
    return {"status": "ok", "message": "Collection deleted"}


# Mount static files last — catch-all for chat UI
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
