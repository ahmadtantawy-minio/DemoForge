Work in a separate git worktree so this doesn't conflict with ongoing work on main. Set it up first:

```
git worktree add ../demoforge-rag feature/rag-pipeline
cd ../demoforge-rag
```

If the branch already exists, use `git worktree add ../demoforge-rag feature/rag-pipeline`. If it doesn't exist yet, create it: `git checkout -b feature/rag-pipeline && git worktree add ../demoforge-rag feature/rag-pipeline`. Work entirely inside `../demoforge-rag` for all changes below.

---

# What to build: RAG Pipeline demo scenario for DemoForge

This adds a Retrieval-Augmented Generation demo: documents go into MinIO, get chunked and embedded via Ollama, vectors stored in Qdrant, a local LLM answers questions with source citations, and every query is audit-logged back to MinIO.

Before making any changes, read these files to confirm the patterns haven't shifted:
- `components/minio/manifest.yaml` — manifest schema reference
- `components/data-generator/manifest.yaml` — custom image with `build_context`, edge config, sub-panel pattern
- `backend/app/engine/compose_generator.py` — find `_edge_env_map` and the S3 edge resolution loop
- `frontend/src/components/properties/PropertiesPanel.tsx` — find `DataGeneratorPanel` as the sub-panel pattern
- `frontend/src/components/canvas/nodes/ComponentNode.tsx` — find data-generator subtitle rendering
- `frontend/src/types/index.ts` — find the `ConnectionType` union type
- `demo-templates/bi-dashboard-lakehouse.yaml` — template structure with `_template:` metadata block

Match every convention exactly. Extend, don't replace.

---

## 1. Create component manifests

### `components/ollama/manifest.yaml`

```yaml
id: ollama
name: Ollama
category: ai
icon: ollama
version: "latest"
image: ollama/ollama:latest
description: "Local LLM inference and embedding generation"

resources:
  memory: "4g"
  cpu: 2.0

ports:
  - name: api
    container: 11434
    protocol: tcp

environment:
  OLLAMA_HOST: "0.0.0.0:11434"

volumes:
  - name: models
    path: /root/.ollama/models
    size: 10g

command: []

health_check:
  endpoint: /api/tags
  port: 11434
  interval: 15s
  timeout: 10s
  start_period: "30s"

secrets: []

web_ui: []

terminal:
  shell: /bin/sh
  welcome_message: "Ollama container. Use 'ollama' CLI to manage models."
  quick_actions:
    - label: "List models"
      command: "ollama list"
    - label: "Pull embedding model"
      command: "ollama pull nomic-embed-text"
    - label: "Pull chat model"
      command: "ollama pull llama3.2:3b"
    - label: "Test chat"
      command: "ollama run llama3.2:3b 'What is object storage?' --nowordwrap"
    - label: "Test embedding"
      command: "curl -s http://localhost:11434/api/embeddings -d '{\"model\":\"nomic-embed-text\",\"prompt\":\"test\"}' | head -c 200"

connections:
  provides:
    - type: llm-api
      port: 11434
      description: "Ollama REST API — chat, generate, and embedding endpoints"
  accepts: []

variants:
  default:
    description: "Standard Ollama with CPU inference"
    command: []

template_mounts: []
static_mounts: []

init_scripts:
  - command: "sh -c 'ollama pull nomic-embed-text && ollama pull llama3.2:3b'"
    wait_for_healthy: true
    timeout: 300
    order: 1
    description: "Pull embedding and chat models (~1.8GB total)"
```

### `components/qdrant/manifest.yaml`

```yaml
id: qdrant
name: Qdrant
category: database
icon: qdrant
version: "latest"
image: qdrant/qdrant:latest
description: "Vector database for similarity search and RAG"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: http
    container: 6333
    protocol: tcp
  - name: grpc
    container: 6334
    protocol: tcp

environment: {}

volumes:
  - name: storage
    path: /qdrant/storage
    size: 2g

command: []

health_check:
  endpoint: /healthz
  port: 6333
  interval: 10s
  timeout: 5s
  start_period: "10s"

secrets:
  - key: QDRANT__SERVICE__API_KEY
    label: "API Key (optional)"
    default: ""
    required: false

web_ui:
  - name: dashboard
    port: 6333
    path: /dashboard
    description: "Qdrant web UI — collection browser, point visualization"

terminal:
  shell: /bin/sh
  welcome_message: "Qdrant vector database container."
  quick_actions:
    - label: "List collections"
      command: "wget -qO- http://localhost:6333/collections 2>/dev/null || echo 'Not ready'"
    - label: "Health check"
      command: "wget -qO- http://localhost:6333/healthz 2>/dev/null || echo 'Not ready'"

connections:
  provides:
    - type: vector-db
      port: 6333
      description: "Qdrant REST API for vector operations"
  accepts:
    - type: s3
      config_schema:
        - key: snapshot_bucket
          label: "Snapshot Bucket"
          type: string
          default: "qdrant-snapshots"
          description: "MinIO bucket for Qdrant snapshot backups"

variants:
  default:
    description: "Single node with local storage"
    command: []

template_mounts: []
static_mounts: []
init_scripts: []
```

### `components/rag-app/manifest.yaml`

```yaml
id: rag-app
name: RAG Pipeline
category: ai
icon: rag
version: "1.0"
image: demoforge/rag-app:latest
build_context: "."
description: "Document ingestion, embedding, and retrieval-augmented generation pipeline"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: api
    container: 8080
    protocol: tcp

environment:
  MINIO_ENDPOINT: ""
  MINIO_ACCESS_KEY: "minioadmin"
  MINIO_SECRET_KEY: "minioadmin"
  OLLAMA_ENDPOINT: ""
  QDRANT_ENDPOINT: ""
  EMBEDDING_MODEL: "nomic-embed-text"
  CHAT_MODEL: "llama3.2:3b"
  CHUNK_SIZE: "500"
  CHUNK_OVERLAP: "50"
  DOCUMENTS_BUCKET: "documents"
  AUDIT_BUCKET: "rag-audit-log"

volumes: []

command: []

health_check:
  endpoint: /health
  port: 8080
  interval: 10s
  timeout: 5s
  start_period: "15s"

secrets:
  - key: MINIO_ACCESS_KEY
    label: "MinIO Access Key"
    default: "minioadmin"
  - key: MINIO_SECRET_KEY
    label: "MinIO Secret Key"
    default: "minioadmin"

web_ui:
  - name: chat
    port: 8080
    path: /
    description: "RAG chat interface — ask questions about your documents"
  - name: api-docs
    port: 8080
    path: /docs
    description: "FastAPI auto-docs for the RAG pipeline API"

terminal:
  shell: /bin/sh
  welcome_message: "RAG pipeline container."
  quick_actions:
    - label: "Pipeline status"
      command: "wget -qO- http://localhost:8080/status 2>/dev/null || echo 'Not ready'"
    - label: "List ingested docs"
      command: "wget -qO- http://localhost:8080/documents 2>/dev/null || echo 'Not ready'"
    - label: "Ingest sample docs"
      command: "wget -qO- --post-data='' http://localhost:8080/ingest/sample 2>/dev/null || echo 'Failed'"
    - label: "Ask test question"
      command: "wget -qO- --post-data='{\"question\":\"What is MinIO?\"}' --header='Content-Type: application/json' http://localhost:8080/ask 2>/dev/null || echo 'Failed'"

connections:
  provides: []
  accepts:
    - type: s3
      config_schema:
        - key: documents_bucket
          label: "Documents Bucket"
          type: string
          default: "documents"
        - key: audit_bucket
          label: "Audit Log Bucket"
          type: string
          default: "rag-audit-log"
    - type: llm-api
      config_schema:
        - key: embedding_model
          label: "Embedding Model"
          type: string
          default: "nomic-embed-text"
        - key: chat_model
          label: "Chat Model"
          type: string
          default: "llama3.2:3b"
    - type: vector-db
      config_schema: []

variants:
  default:
    description: "Full RAG pipeline with chat UI"
    command: []

template_mounts: []
static_mounts: []

init_scripts:
  - command: "sh -c 'until wget -qO- http://localhost:8080/health 2>/dev/null | grep ok; do sleep 3; done && wget -qO- --post-data=\"\" http://localhost:8080/ingest/sample 2>/dev/null'"
    wait_for_healthy: true
    timeout: 120
    order: 2
    description: "Ingest sample MinIO documentation for demo"
```

---

## 2. Build the rag-app container

Create `components/rag-app/` with:

```
components/rag-app/
  manifest.yaml
  Dockerfile
  requirements.txt
  app/
    main.py
    config.py
    pipeline/
      ingestion.py
      chunker.py
      embedder.py
      retriever.py
      generator.py
      audit.py
    models.py
    sample_docs/
      minio-overview.txt
      object-storage-guide.txt
      aistor-tables-faq.txt
      erasure-coding-explained.txt
      s3-api-reference.txt
    static/
      index.html
```

### Dockerfile

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### requirements.txt

```
fastapi==0.115.12
uvicorn[standard]==0.34.0
boto3==1.35.0
httpx==0.28.1
qdrant-client==1.12.0
pydantic==2.11.1
python-multipart==0.0.18
pypdf2==3.0.1
```

### app/config.py

Read everything from env vars — the compose generator sets these from edge resolution.

```python
import os

class Settings:
    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
    QDRANT_ENDPOINT = os.getenv("QDRANT_ENDPOINT", "http://localhost:6333")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    CHAT_MODEL = os.getenv("CHAT_MODEL", "llama3.2:3b")
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
    DOCUMENTS_BUCKET = os.getenv("DOCUMENTS_BUCKET", "documents")
    AUDIT_BUCKET = os.getenv("AUDIT_BUCKET", "rag-audit-log")

settings = Settings()
```

### app/main.py

FastAPI app. Mount static files AFTER API routes so `/health`, `/ask` etc. take priority over the catch-all HTML:

```python
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
```

**Endpoints:**

| Route | Method | Behavior |
|-------|--------|----------|
| `/health` | GET | `{"status":"ok", "minio_connected": bool, "qdrant_connected": bool, "models_loaded": bool}` |
| `/status` | GET | `{"documents_ingested": N, "chunks_stored": N, "embedding_model": "...", "chat_model": "..."}` |
| `/ingest/upload` | POST | Multipart file upload → MinIO → extract → chunk → embed → Qdrant |
| `/ingest/sample` | POST | Upload bundled `sample_docs/` to MinIO and ingest them |
| `/ingest/bucket` | POST | `{"bucket": "documents"}` → scan and ingest un-processed files |
| `/documents` | GET | `[{"filename": "...", "chunks": N, "ingested_at": "..."}, ...]` |
| `/ask` | POST | `{"question": "...", "top_k": 5}` → embed → Qdrant search → build prompt → Ollama chat → return answer + sources |
| `/history` | GET | Last 50 queries from MinIO audit bucket |
| `/collection` | DELETE | Drop Qdrant collection (demo reset) |

### Pipeline modules

**`pipeline/ingestion.py`** — boto3 S3 client with `endpoint_url=settings.MINIO_ENDPOINT`, `signature_version='s3v4'`, path-style access. `extract_text()`: .pdf→PyPDF2, .txt/.md→UTF-8 decode, .json→extract string values.

**`pipeline/chunker.py`** — `chunk_text(text, chunk_size, overlap)`: split by sentences (`r'(?<=[.!?])\s+'`), accumulate to chunk_size chars, slide back by overlap. Returns `[{"text": "...", "index": N}]`.

**`pipeline/embedder.py`** — `embed_text(text)`: POST to `{OLLAMA_ENDPOINT}/api/embeddings` with `{"model": model, "prompt": text}`. Returns 768-dim vector. Process chunks sequentially (Ollama is single-threaded on CPU).

**`pipeline/retriever.py`** — Uses `qdrant_client.QdrantClient(url=settings.QDRANT_ENDPOINT)`. `ensure_collection()`: create if not exists, cosine distance, 768 dims. `store_vectors()`: upsert points with payload `{text, filename, chunk_index, ingested_at}`, UUID point IDs. `search()`: returns `[{text, filename, score}]`.

**`pipeline/generator.py`** — `generate_answer(question, context_chunks)`: build prompt with system message ("Answer based ONLY on context, cite sources"), context chunks each prefixed with `[Source: filename]`, then the question. POST to `{OLLAMA_ENDPOINT}/api/chat` with `{"model": model, "messages": [...], "stream": false}`. Return `{"answer": "...", "tokens": N}`.

**`pipeline/audit.py`** — `log_query(question, answer, sources, latency_ms)`: build JSON record, upload to MinIO at `{AUDIT_BUCKET}/{date}/{timestamp}_{uuid}.json`.

### Sample documents

Create 5 text files in `app/sample_docs/`, 500-800 words each, factually accurate:

1. **`minio-overview.txt`** — MinIO, AIStor, S3 compatibility, distributed architecture, erasure coding, exabyte-scale, sub-10ms latency
2. **`object-storage-guide.txt`** — Object vs file vs block, S3 concepts (buckets, objects, metadata, versioning), AI/ML use cases
3. **`aistor-tables-faq.txt`** — AIStor Tables = built-in Iceberg V3 REST Catalog, no external catalog needed, multi-engine (Spark, Trino, Dremio), vs AWS S3 Tables
4. **`erasure-coding-explained.txt`** — K+M shards, EC:4 = 4+4 tolerates 4 failures, EC:8 = 8+4, read/write quorum, immutable after deploy, max 16 drives per set
5. **`s3-api-reference.txt`** — PutObject, GetObject, ListObjectsV2, SigV4 auth, multipart upload, presigned URLs, bucket notifications, object locking

Must contain enough specific facts for test questions like "How many drive failures with EC:4?" → answer must be "4".

### Chat UI — `app/static/index.html`

Single HTML file, no build step, vanilla JS with fetch(). Features:
- Chat message list, input field + send button (Enter to send)
- Each answer shows response text + collapsible "Sources" section with filenames and scores
- Status bar: MinIO/Qdrant/Ollama connection dots (poll `/status` every 10s)
- Buttons: "Load sample docs" (POST /ingest/sample), "Upload document" (file picker → POST /ingest/upload), "Reset" (DELETE /collection)
- "Thinking..." with animated dots while waiting for `/ask`
- Transparent/light background — it'll be served inside DemoForge's proxy iframe

---

## 3. Backend: compose generator edge resolution

File: `backend/app/engine/compose_generator.py`

Find the edge resolution loop where S3 endpoints are auto-resolved. Add two new connection types following the same pattern:

**Add to `_edge_env_map`:**

```python
"documents_bucket": "DOCUMENTS_BUCKET",
"audit_bucket": "AUDIT_BUCKET",
"snapshot_bucket": "QDRANT_SNAPSHOT_BUCKET",
"embedding_model": "EMBEDDING_MODEL",
"chat_model": "CHAT_MODEL",
```

**Add `llm-api` resolution** in the edge loop (after the S3 block):

```python
if edge.connection_type == "llm-api":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        llm_port = next((p.container for p in peer_manifest.ports if p.name == "api"), 11434)
        env["OLLAMA_ENDPOINT"] = f"http://{project_name}-{peer_id}:{llm_port}"
    edge_cfg = edge.connection_config or {}
    if edge_cfg.get("embedding_model"):
        env["EMBEDDING_MODEL"] = edge_cfg["embedding_model"]
    if edge_cfg.get("chat_model"):
        env["CHAT_MODEL"] = edge_cfg["chat_model"]
```

**Add `vector-db` resolution:**

```python
if edge.connection_type == "vector-db":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        vdb_port = next((p.container for p in peer_manifest.ports if p.name == "http"), 6333)
        env["QDRANT_ENDPOINT"] = f"http://{project_name}-{peer_id}:{vdb_port}"
```

**For S3 edges to rag-app**, also forward credentials:

```python
if node_component == "rag-app" and peer_component in ("minio", "minio-aistore"):
    env["MINIO_ACCESS_KEY"] = peer_env.get("MINIO_ROOT_USER", "minioadmin")
    env["MINIO_SECRET_KEY"] = peer_env.get("MINIO_ROOT_PASSWORD", "minioadmin")
```

Where `peer_env` is the resolved environment for the MinIO node — check how the existing code accesses peer node config to get credentials.

---

## 4. Frontend: new connection types

File: `frontend/src/types/index.ts`

Add to the `ConnectionType` union:

```typescript
| "llm-api" | "vector-db"
```

---

## 5. Frontend: properties panel sub-panels

File: `frontend/src/components/properties/PropertiesPanel.tsx`

Follow the `DataGeneratorPanel` pattern exactly.

**Add `RagAppPanel`:**

```tsx
function RagAppPanel({ nodeId, demoId, isRunning, config, updateConfig }) {
  const [ragStatus, setRagStatus] = useState<any>(null);

  useEffect(() => {
    if (!isRunning || !demoId) return;
    const poll = setInterval(async () => {
      try {
        const result = await execCommand(demoId, nodeId,
          "wget -qO- http://localhost:8080/status 2>/dev/null");
        if (result.exit_code === 0) setRagStatus(JSON.parse(result.stdout));
      } catch {}
    }, 5000);
    return () => clearInterval(poll);
  }, [isRunning, demoId, nodeId]);

  const handleIngestSample = async () => {
    await execCommand(demoId, nodeId,
      "wget -qO- --post-data='' http://localhost:8080/ingest/sample 2>/dev/null");
  };

  const handleAskTest = async () => {
    await execCommand(demoId, nodeId,
      "wget -qO- --post-data='{\"question\":\"What is MinIO?\"}' --header='Content-Type: application/json' http://localhost:8080/ask 2>/dev/null");
  };

  const handleReset = async () => {
    await execCommand(demoId, nodeId,
      "wget -qO- --method=DELETE http://localhost:8080/collection 2>/dev/null");
  };

  return (
    <div className="space-y-3 mt-3">
      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider">RAG Pipeline</div>

      {ragStatus && (
        <>
          <div className="space-y-1 text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.minio_connected ? 'bg-green-500' : 'bg-red-500'}`} />
              MinIO
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.qdrant_connected ? 'bg-green-500' : 'bg-red-500'}`} />
              Qdrant
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${ragStatus.models_loaded ? 'bg-green-500' : 'bg-yellow-400 animate-pulse'}`} />
              Ollama models
            </div>
          </div>
          <div className="text-xs text-muted-foreground space-y-0.5">
            <div>Documents: {ragStatus.documents_ingested}</div>
            <div>Chunks: {ragStatus.chunks_stored}</div>
          </div>
        </>
      )}

      {isRunning && (
        <div className="space-y-1.5">
          <button onClick={handleIngestSample}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted">
            Load sample docs
          </button>
          <button onClick={handleAskTest}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted">
            Ask test question
          </button>
          <button onClick={handleReset}
            className="w-full text-xs h-7 px-2 rounded border border-border bg-background hover:bg-muted text-destructive">
            Reset collection
          </button>
        </div>
      )}
    </div>
  );
}
```

Add to the main render:

```tsx
{nodeData.componentId === "rag-app" && (
  <RagAppPanel nodeId={selectedNodeId} demoId={activeDemoId} isRunning={isRunning} config={nodeData.config} updateConfig={updateConfig} />
)}
```

**Add `OllamaPanel`** — same pattern, polls `ollama list` via execCommand, shows which models are downloaded.

---

## 6. Frontend: node subtitles

File: `frontend/src/components/canvas/nodes/ComponentNode.tsx`

Add alongside the existing data-generator subtitle block:

```tsx
{nodeData.componentId === "rag-app" && isRunning && ragStatus && (
  <div className="text-[10px] text-muted-foreground/70 leading-tight mt-0.5">
    {ragStatus.documents_ingested} docs / {ragStatus.chunks_stored} chunks
  </div>
)}

{nodeData.componentId === "ollama" && isRunning && (
  <div className="text-[10px] text-muted-foreground/70 leading-tight mt-0.5">
    {modelsReady ? "Models ready" : "Downloading..."}
  </div>
)}
```

The polling logic for `ragStatus` and `modelsReady` follows the same pattern as the data-generator's `genRunning` check — poll via `execCommand` on an interval when `isRunning` is true.

---

## 7. Demo template

Create `demo-templates/rag-pipeline.yaml`:

```yaml
_template:
  name: "RAG Pipeline — Enterprise AI on MinIO"
  category: "ai"
  tags: ["rag", "llm", "ollama", "qdrant", "vector-db", "ai", "embeddings"]
  description: "Documents stored in MinIO, embedded via Ollama, vectors in Qdrant, local LLM answers questions. Full audit trail in MinIO."
  objective: "Demonstrate MinIO as the unified data foundation for a RAG pipeline"
  minio_value: "MinIO serves as the single data layer: source documents, vector DB snapshots, and query audit trails."
  estimated_resources:
    memory: "6GB"
    cpu: 4
    containers: 4
  walkthrough:
    - step: "Deploy the demo"
      description: "Click Deploy. Wait for all 4 components to turn green. Ollama downloads models (~1.8GB) on first run."
    - step: "Verify models"
      description: "Click Ollama node — properties should show nomic-embed-text and llama3.2:3b."
    - step: "Load sample documents"
      description: "Click RAG Pipeline node → 'Load sample docs'. Uploads 5 MinIO docs, creates ~130 embeddings."
    - step: "Ask questions"
      description: "Open Chat UI. Ask: 'How many drive failures can MinIO tolerate with EC:4?' — answer cites erasure-coding doc."
    - step: "Check audit trail"
      description: "Open MinIO Console → rag-audit-log bucket. Each question is logged as JSON."
    - step: "Upload your own document"
      description: "In chat UI, upload any PDF or text file, then ask about its content."
    - step: "Inspect vectors"
      description: "Open Qdrant Dashboard → documents collection — each point is a text chunk."
  external_dependencies:
    - "Internet required for first Ollama model download (~1.8GB). Cached on subsequent deploys."

id: template-rag-pipeline
name: "RAG Pipeline — Enterprise AI on MinIO"
description: "Documents in MinIO, embeddings via Ollama, vectors in Qdrant, LLM answers with citations. Full audit trail."

networks:
  - name: default
    subnet: 172.20.0.0/16
    driver: bridge

nodes:
  - id: minio-1
    component: minio
    variant: single
    position: {x: 100, y: 250}
    display_name: "MinIO"
    config:
      MINIO_ROOT_USER: "minioadmin"
      MINIO_ROOT_PASSWORD: "minioadmin"

  - id: ollama-1
    component: ollama
    variant: default
    position: {x: 400, y: 50}
    display_name: "Ollama"

  - id: qdrant-1
    component: qdrant
    variant: default
    position: {x: 400, y: 450}
    display_name: "Qdrant"

  - id: rag-1
    component: rag-app
    variant: default
    position: {x: 700, y: 250}
    display_name: "RAG Pipeline"

clusters: []

edges:
  - id: e-rag-minio
    source: rag-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Docs + audit logs"
    connection_config:
      documents_bucket: "documents"
      audit_bucket: "rag-audit-log"

  - id: e-rag-ollama
    source: rag-1
    target: ollama-1
    connection_type: llm-api
    auto_configure: true
    label: "Embed + generate"
    connection_config:
      embedding_model: "nomic-embed-text"
      chat_model: "llama3.2:3b"

  - id: e-rag-qdrant
    source: rag-1
    target: qdrant-1
    connection_type: vector-db
    auto_configure: true
    label: "Vector search"

  - id: e-qdrant-minio
    source: qdrant-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Snapshot backup"
    connection_config:
      snapshot_bucket: "qdrant-snapshots"

groups: []
sticky_notes: []

resources:
  default_memory: "512m"
  default_cpu: 0.5
  max_memory: "4g"
  max_cpu: 2.0
  total_memory: "8g"
  total_cpu: 6.0
```

**Edge direction note:** Check `demo-templates/bi-dashboard-lakehouse.yaml` — the `data-gen → minio-1` edge has `source: data-gen, target: minio-1`. If the convention is source=producer/consumer (the one initiating the connection), keep the edges above as-is. If it's source=provider, swap them. Match the existing convention.

---

## 8. Verification

After building, deploy the template and run through these tests:

**Test 1 — Deploy:** Load RAG Pipeline template → Deploy → all 4 nodes green → Ollama shows models downloaded → MinIO has `documents`, `rag-audit-log` buckets.

**Test 2 — Ingest:** Click rag-1 → "Load sample docs" → status shows "5 docs / ~130 chunks" → MinIO `documents` bucket has 5 files → Qdrant dashboard shows ~130 points.

**Test 3 — Q&A:** Open Chat UI → ask "How many drive failures with EC:4?" → answer says "4", cites `erasure-coding-explained.txt` → ask "Does AIStor Tables need an external catalog?" → answer says "no", cites `aistor-tables-faq.txt`.

**Test 4 — Audit:** MinIO Console → `rag-audit-log` → JSON files for each question → download one → valid JSON with question, answer, sources, latency.

---

## What NOT to do

- Don't use LangChain or LlamaIndex — direct HTTP to Ollama, qdrant-client library for Qdrant
- Don't stream Ollama responses — `"stream": false`
- Don't modify existing manifests (minio, data-generator, trino, etc.)
- Don't put the chat UI behind a build step — single HTML file, StaticFiles mount
- Don't hardcode hostnames — env vars only, set by compose generator
- Don't add GPU support — CPU inference with small models
- Don't create files in `demos/` — template goes in `demo-templates/`
