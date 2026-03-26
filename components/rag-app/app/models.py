from pydantic import BaseModel

class AskRequest(BaseModel):
    question: str
    top_k: int = 5

class SourceInfo(BaseModel):
    filename: str
    text: str
    score: float

class AskResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    latency_ms: int
    tokens: int = 0

class IngestResponse(BaseModel):
    files_processed: int
    chunks_created: int
    message: str = ""

class DocumentInfo(BaseModel):
    filename: str
    chunks: int
    ingested_at: str

class HealthResponse(BaseModel):
    status: str
    minio_connected: bool
    qdrant_connected: bool
    models_loaded: bool

class StatusResponse(BaseModel):
    documents_ingested: int
    chunks_stored: int
    embedding_model: str
    chat_model: str
