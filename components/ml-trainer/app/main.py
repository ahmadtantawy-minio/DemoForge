import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ML Trainer", version="1.0")

_state = {"status": "idle", "last_result": None}


class QuickTrainRequest(BaseModel):
    n_runs: int = 3


class SweepRequest(BaseModel):
    n_variations: int = 12


@app.get("/health")
async def health():
    mlflow_ok = False
    minio_ok = False
    try:
        from .pipeline.data_prep import get_s3_client
        client = get_s3_client()
        client.list_buckets()
        minio_ok = True
    except Exception:
        pass
    try:
        import httpx
        resp = httpx.get(f"{settings.MLFLOW_TRACKING_URI}/health", timeout=5.0)
        mlflow_ok = resp.status_code == 200
    except Exception:
        pass
    return {"status": "ok", "minio_connected": minio_ok, "mlflow_connected": mlflow_ok}


@app.get("/status")
async def status():
    return {**_state, "experiment_name": settings.EXPERIMENT_NAME,
            "training_bucket": settings.TRAINING_BUCKET}


@app.post("/prepare-data")
async def prepare_data():
    try:
        from .pipeline.data_prep import load_training_data, prepare_train_test
        _state["status"] = "preparing"
        df = load_training_data("raw-data")
        result = prepare_train_test(df)
        _state["status"] = "ready"
        _state["last_result"] = {"action": "prepare", **result}
        return result
    except Exception as e:
        _state["status"] = "error"
        logger.error(f"Data preparation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train/quick")
async def train_quick(req: QuickTrainRequest):
    try:
        from .pipeline.trainer import run_quick_training
        _state["status"] = "training"
        results = run_quick_training(req.n_runs)
        _state["status"] = "idle"
        _state["last_result"] = {"action": "quick_train", "runs": results}
        return {"runs": results}
    except Exception as e:
        _state["status"] = "error"
        logger.error(f"Quick training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train/sweep")
async def train_sweep(req: SweepRequest):
    try:
        from .pipeline.trainer import run_sweep
        _state["status"] = "sweeping"
        result = run_sweep(req.n_variations)
        _state["status"] = "idle"
        _state["last_result"] = {"action": "sweep", **result}
        return result
    except Exception as e:
        _state["status"] = "error"
        logger.error(f"Sweep failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Static dashboard
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
