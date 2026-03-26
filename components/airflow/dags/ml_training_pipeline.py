"""
ML Training Pipeline DAG
Orchestrates: check data → prepare features → train model → register best
All operations call the ML Trainer API which reads/writes to MinIO.
"""
import os
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import requests

TRAINER_URL = os.getenv("AIRFLOW_API_URL", "http://localhost:8090")

default_args = {
    "owner": "demoforge",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "ml_training_pipeline",
    default_args=default_args,
    description="End-to-end ML pipeline: data prep → training → model registration",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ml", "training", "minio"],
)


def check_data(**context):
    """Verify raw data exists in MinIO via the trainer's health endpoint."""
    resp = requests.get(f"{TRAINER_URL}/health", timeout=30)
    resp.raise_for_status()
    health = resp.json()
    if not health.get("minio_connected"):
        raise Exception("MinIO is not connected")
    print(f"Data check passed: MinIO connected={health['minio_connected']}")


def prepare_features(**context):
    """Call ML Trainer to prepare train/test split from raw data."""
    resp = requests.post(f"{TRAINER_URL}/prepare-data", timeout=120)
    resp.raise_for_status()
    result = resp.json()
    print(f"Data prepared: {result.get('train_rows', 0)} train / {result.get('test_rows', 0)} test rows")
    return result


def train_model(**context):
    """Run quick training (3 models) via ML Trainer."""
    resp = requests.post(
        f"{TRAINER_URL}/train/quick",
        json={"n_runs": 3},
        timeout=300,
    )
    resp.raise_for_status()
    result = resp.json()
    runs = result.get("runs", [])
    for run in runs:
        print(f"  {run['model']}: RMSE={run['rmse']:.4f}, R2={run['r2']:.4f}")
    return result


def register_best(**context):
    """Run hyperparameter sweep and register the best model in MLflow."""
    resp = requests.post(
        f"{TRAINER_URL}/train/sweep",
        json={"n_variations": 12},
        timeout=600,
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"Sweep complete: {result.get('total_runs', 0)} runs, best RMSE={result.get('best_rmse', 0):.4f}")
    return result


t1 = PythonOperator(task_id="check_data", python_callable=check_data, dag=dag)
t2 = PythonOperator(task_id="prepare_features", python_callable=prepare_features, dag=dag)
t3 = PythonOperator(task_id="train_model", python_callable=train_model, dag=dag)
t4 = PythonOperator(task_id="register_best", python_callable=register_best, dag=dag)

t1 >> t2 >> t3 >> t4
