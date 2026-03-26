import os
import io
import logging
import time
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from ..config import settings
from .data_prep import load_split

logger = logging.getLogger(__name__)


def _setup_mlflow():
    os.environ["MLFLOW_TRACKING_URI"] = settings.MLFLOW_TRACKING_URI
    os.environ["MLFLOW_S3_ENDPOINT_URL"] = settings.MLFLOW_S3_ENDPOINT_URL
    os.environ["AWS_ACCESS_KEY_ID"] = settings.AWS_ACCESS_KEY_ID
    os.environ["AWS_SECRET_ACCESS_KEY"] = settings.AWS_SECRET_ACCESS_KEY
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    mlflow.set_experiment(settings.EXPERIMENT_NAME)


def _prepare_features(df: pd.DataFrame) -> tuple:
    """Prepare features for training. Handles ecommerce-orders schema."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    # Try to predict total_amount or quantity
    target_col = None
    for col in ["total_amount", "quantity", "price"]:
        if col in numeric_cols:
            target_col = col
            break
    if not target_col:
        target_col = numeric_cols[-1]

    feature_cols = [c for c in numeric_cols if c != target_col]
    if not feature_cols:
        raise ValueError("No numeric feature columns found")

    X = df[feature_cols].fillna(0)
    y = df[target_col].fillna(0)
    return X, y, feature_cols, target_col


def run_quick_training(n_runs: int = 3) -> list:
    """Run 3+ quick experiments with different models."""
    _setup_mlflow()
    train_df = load_split("train")
    test_df = load_split("test")
    X_train, y_train, feature_cols, target_col = _prepare_features(train_df)
    X_test, y_test, _, _ = _prepare_features(test_df)

    models = [
        ("RandomForest", RandomForestRegressor(n_estimators=50, max_depth=10, random_state=42)),
        ("GradientBoosting", GradientBoostingRegressor(n_estimators=50, max_depth=5, random_state=42)),
        ("LinearRegression", LinearRegression()),
    ]

    results = []
    for name, model in models[:n_runs]:
        with mlflow.start_run(run_name=name):
            start = time.time()
            model.fit(X_train, y_train)
            train_time = time.time() - start

            y_pred = model.predict(X_test)
            rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
            mae = float(mean_absolute_error(y_test, y_pred))
            r2 = float(r2_score(y_test, y_pred))

            mlflow.log_param("model_type", name)
            mlflow.log_param("n_features", len(feature_cols))
            mlflow.log_param("target", target_col)
            mlflow.log_param("train_rows", len(X_train))
            mlflow.log_metric("rmse", rmse)
            mlflow.log_metric("mae", mae)
            mlflow.log_metric("r2", r2)
            mlflow.log_metric("train_time_seconds", train_time)
            mlflow.sklearn.log_model(model, "model")

            # Log feature importance if available
            if hasattr(model, "feature_importances_"):
                try:
                    import matplotlib
                    matplotlib.use("Agg")
                    import matplotlib.pyplot as plt
                    fig, ax = plt.subplots(figsize=(8, 4))
                    importance = model.feature_importances_
                    ax.barh(feature_cols, importance)
                    ax.set_title(f"{name} Feature Importance")
                    buf = io.BytesIO()
                    fig.savefig(buf, format="png", bbox_inches="tight")
                    buf.seek(0)
                    mlflow.log_figure(fig, "feature_importance.png")
                    plt.close(fig)
                except Exception as e:
                    logger.warning(f"Failed to log feature importance: {e}")

            results.append({
                "model": name, "rmse": rmse, "mae": mae, "r2": r2,
                "train_time": round(train_time, 2),
            })
            logger.info(f"{name}: RMSE={rmse:.4f}, MAE={mae:.4f}, R2={r2:.4f}")

    return results


def run_sweep(n_variations: int = 12) -> dict:
    """Run hyperparameter sweep, register best model."""
    _setup_mlflow()
    train_df = load_split("train")
    test_df = load_split("test")
    X_train, y_train, feature_cols, target_col = _prepare_features(train_df)
    X_test, y_test, _, _ = _prepare_features(test_df)

    configs = []
    for n_est in [25, 50, 100, 200]:
        for max_d in [5, 10, 15]:
            configs.append({"n_estimators": n_est, "max_depth": max_d})

    best_rmse = float("inf")
    best_run_id = None
    results = []

    for i, cfg in enumerate(configs[:n_variations]):
        with mlflow.start_run(run_name=f"RF_sweep_{i+1}"):
            model = RandomForestRegressor(**cfg, random_state=42)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
            r2 = float(r2_score(y_test, y_pred))

            mlflow.log_params(cfg)
            mlflow.log_param("target", target_col)
            mlflow.log_metric("rmse", rmse)
            mlflow.log_metric("r2", r2)
            mlflow.sklearn.log_model(model, "model")

            run_id = mlflow.active_run().info.run_id
            results.append({"run_id": run_id, "config": cfg, "rmse": rmse, "r2": r2})

            if rmse < best_rmse:
                best_rmse = rmse
                best_run_id = run_id

    # Register best model
    if best_run_id:
        try:
            model_uri = f"runs:/{best_run_id}/model"
            mlflow.register_model(model_uri, "best-ecommerce-model")
            logger.info(f"Registered best model from run {best_run_id} (RMSE={best_rmse:.4f})")
        except Exception as e:
            logger.warning(f"Model registration failed: {e}")

    return {
        "total_runs": len(results),
        "best_run_id": best_run_id,
        "best_rmse": best_rmse,
        "results": results,
    }
