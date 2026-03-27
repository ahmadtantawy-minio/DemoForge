# Claude Code Instruction: AI/ML Ecosystem Components & Demo Templates

Work in a git worktree:

```
git worktree add ../demoforge-ai-ecosystem feature/ai-ecosystem
cd ../demoforge-ai-ecosystem
```

## Context

DemoForge is running with analytics demos (AIStor Tables, Trino, Metabase) and the RAG pipeline (Ollama, Qdrant, rag-app). The data-generator has a dataset catalog with three scenarios (ecommerce-orders, iot-telemetry, financial-txn) and supports Parquet/JSON/CSV/Iceberg formats.

This instruction adds recognized commercial/open-source AI tools that integrate natively with MinIO via S3, plus demo templates that combine them into coherent stories with data generation.

Before making changes, read:
- `components/minio/manifest.yaml` — manifest schema
- `components/data-generator/manifest.yaml` — custom image, edge config
- `components/rag-app/manifest.yaml` — the RAG pattern you're extending
- `backend/app/engine/compose_generator.py` — edge resolution
- `frontend/src/types/index.ts` — `ConnectionType` union
- `demo-templates/rag-pipeline.yaml` — template structure

---

## Part 1: Component Manifests

### 1.1 MLflow — `components/mlflow/manifest.yaml`

```yaml
id: mlflow
name: MLflow
category: ai
icon: mlflow
version: "latest"
image: ghcr.io/mlflow/mlflow:latest
description: "ML experiment tracking, model registry, and artifact management"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: web
    container: 5000
    protocol: tcp

environment:
  MLFLOW_S3_ENDPOINT_URL: ""
  AWS_ACCESS_KEY_ID: "minioadmin"
  AWS_SECRET_ACCESS_KEY: "minioadmin"
  MLFLOW_S3_IGNORE_TLS: "true"
  MLFLOW_ARTIFACTS_DESTINATION: "s3://mlflow-artifacts/"
  MLFLOW_BACKEND_STORE_URI: "sqlite:///mlflow/mlflow.db"

volumes:
  - name: data
    path: /mlflow
    size: 1g

command: ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000",
          "--backend-store-uri", "sqlite:///mlflow/mlflow.db",
          "--default-artifact-root", "s3://mlflow-artifacts/",
          "--serve-artifacts",
          "--artifacts-destination", "s3://mlflow-artifacts/"]

health_check:
  endpoint: /health
  port: 5000
  interval: 10s
  timeout: 5s
  start_period: "15s"

secrets:
  - key: AWS_ACCESS_KEY_ID
    label: "MinIO Access Key"
    default: "minioadmin"
  - key: AWS_SECRET_ACCESS_KEY
    label: "MinIO Secret Key"
    default: "minioadmin"

web_ui:
  - name: dashboard
    port: 5000
    path: /
    description: "MLflow UI — experiments, runs, model registry, artifact browser"

terminal:
  shell: /bin/bash
  welcome_message: "MLflow tracking server. Artifacts stored in MinIO."
  quick_actions:
    - label: "List experiments"
      command: "mlflow experiments search 2>/dev/null || echo 'Server starting...'"
    - label: "Check MinIO connection"
      command: "python3 -c \"import boto3; s3=boto3.client('s3', endpoint_url='$MLFLOW_S3_ENDPOINT_URL', aws_access_key_id='$AWS_ACCESS_KEY_ID', aws_secret_access_key='$AWS_SECRET_ACCESS_KEY'); print(s3.list_buckets()['Buckets'])\""
    - label: "Server status"
      command: "curl -s http://localhost:5000/health || echo 'Not ready'"

connections:
  provides:
    - type: mlflow-tracking
      port: 5000
      description: "MLflow Tracking API — log experiments, register models"
  accepts:
    - type: s3
      config_schema:
        - key: artifact_bucket
          label: "Artifact Bucket"
          type: string
          default: "mlflow-artifacts"

variants:
  default:
    description: "SQLite backend (single-node, simple)"
    command: ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000",
              "--backend-store-uri", "sqlite:///mlflow/mlflow.db",
              "--default-artifact-root", "s3://mlflow-artifacts/",
              "--serve-artifacts",
              "--artifacts-destination", "s3://mlflow-artifacts/"]
  with-postgres:
    description: "PostgreSQL backend (multi-user, production-like)"
    command: ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000",
              "--backend-store-uri", "postgresql://mlflow:mlflow@postgres:5432/mlflow",
              "--default-artifact-root", "s3://mlflow-artifacts/",
              "--serve-artifacts",
              "--artifacts-destination", "s3://mlflow-artifacts/"]

template_mounts: []
static_mounts: []

init_scripts:
  - command: "sh -c 'pip install boto3 psycopg2-binary 2>/dev/null; echo done'"
    wait_for_healthy: false
    timeout: 60
    order: 0
    description: "Install S3 and PostgreSQL drivers"
```

### 1.2 JupyterLab — `components/jupyterlab/manifest.yaml`

```yaml
id: jupyterlab
name: JupyterLab
category: ai
icon: jupyter
version: "latest"
image: demoforge/jupyterlab:latest
build_context: "."
description: "Interactive notebooks for data science, ML training, and MinIO data exploration"

resources:
  memory: "1g"
  cpu: 1.0

ports:
  - name: web
    container: 8888
    protocol: tcp

environment:
  JUPYTER_TOKEN: "demoforge"
  MINIO_ENDPOINT: ""
  MINIO_ACCESS_KEY: "minioadmin"
  MINIO_SECRET_KEY: "minioadmin"
  MLFLOW_TRACKING_URI: ""
  MLFLOW_S3_ENDPOINT_URL: ""
  AWS_ACCESS_KEY_ID: "minioadmin"
  AWS_SECRET_ACCESS_KEY: "minioadmin"

volumes:
  - name: notebooks
    path: /home/jovyan/work
    size: 2g

command: ["start-notebook.py", "--NotebookApp.token=demoforge",
          "--NotebookApp.allow_origin=*", "--ServerApp.disable_check_xsrf=True"]

health_check:
  endpoint: /api/status
  port: 8888
  interval: 15s
  timeout: 5s
  start_period: "20s"

secrets:
  - key: JUPYTER_TOKEN
    label: "Access Token"
    default: "demoforge"

web_ui:
  - name: lab
    port: 8888
    path: /lab
    description: "JupyterLab IDE — notebooks, terminal, file browser"

terminal:
  shell: /bin/bash
  welcome_message: "JupyterLab container. Pre-installed: boto3, pyarrow, pandas, scikit-learn, mlflow."
  quick_actions:
    - label: "List notebooks"
      command: "ls -la /home/jovyan/work/*.ipynb 2>/dev/null || echo 'No notebooks yet'"
    - label: "Test MinIO connection"
      command: "python3 -c \"import boto3; s3=boto3.client('s3', endpoint_url='$MINIO_ENDPOINT', aws_access_key_id='$MINIO_ACCESS_KEY', aws_secret_access_key='$MINIO_SECRET_KEY'); print([b['Name'] for b in s3.list_buckets()['Buckets']])\""

connections:
  provides: []
  accepts:
    - type: s3
      config_schema:
        - key: bucket
          label: "Default Bucket"
          type: string
          default: "data"
    - type: mlflow-tracking
      config_schema: []
    - type: iceberg-catalog
      config_schema: []

variants:
  default:
    description: "Data science stack (pandas, scikit-learn, pyarrow, boto3, mlflow)"
    command: ["start-notebook.py", "--NotebookApp.token=demoforge",
              "--NotebookApp.allow_origin=*", "--ServerApp.disable_check_xsrf=True"]

template_mounts: []
static_mounts: []
init_scripts: []
```

**Custom Dockerfile** — `components/jupyterlab/Dockerfile`:

```dockerfile
FROM jupyter/minimal-notebook:latest

USER root
RUN pip install --no-cache-dir \
    boto3==1.35.0 \
    pyarrow==17.0.0 \
    pandas==2.2.3 \
    scikit-learn==1.5.2 \
    mlflow==2.17.0 \
    matplotlib==3.9.2 \
    seaborn==0.13.2 \
    pyiceberg[s3]==0.7.1 \
    qdrant-client==1.12.0 \
    httpx==0.28.1

# Pre-load sample notebooks
COPY notebooks/ /home/jovyan/work/
RUN chown -R jovyan:users /home/jovyan/work/

USER jovyan
```

**Pre-loaded notebooks** — `components/jupyterlab/notebooks/`:

Create these Jupyter notebooks (`.ipynb`) that demonstrate MinIO integration:

1. **`01-minio-basics.ipynb`** — Connect to MinIO with boto3, list buckets, upload/download files, create presigned URLs. Every cell runs and produces output.

2. **`02-data-exploration.ipynb`** — Read Parquet files from MinIO with pyarrow, load into pandas, basic EDA (describe, value_counts, histograms), write processed data back to MinIO.

3. **`03-ml-training.ipynb`** — Load data from MinIO, train a scikit-learn model (RandomForest on ecommerce-orders data to predict total_amount), log to MLflow (params, metrics, model artifact), compare runs. Shows `mlflow.set_tracking_uri()`, `mlflow.log_param()`, `mlflow.log_metric()`, `mlflow.sklearn.log_model()`.

4. **`04-feature-engineering.ipynb`** — Read raw data from MinIO, compute features (rolling averages, categorical encoding, time-based features), write feature dataset back to MinIO as Parquet. Demonstrates the "raw → features → training" pipeline.

5. **`05-aistor-tables.ipynb`** — Connect to AIStor Tables via PyIceberg, query Iceberg tables, show schema evolution, time-travel queries. Only works when connected to an AIStor Tables-enabled MinIO.

Each notebook should read connection settings from environment variables (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, etc.) so they work without modification when deployed via DemoForge.

### 1.3 Label Studio — `components/label-studio/manifest.yaml`

```yaml
id: label-studio
name: Label Studio
category: ai
icon: label-studio
version: "latest"
image: heartexlabs/label-studio:latest
description: "Multi-type data labeling and annotation tool with S3 storage"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: web
    container: 8080
    protocol: tcp

environment:
  LABEL_STUDIO_HOST: "http://localhost:8080"
  LABEL_STUDIO_USERNAME: "demo@demoforge.local"
  LABEL_STUDIO_PASSWORD: "DemoForge123!"
  LABEL_STUDIO_USER_TOKEN: ""
  DJANGO_DB: "sqlite"
  LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED: "true"
  LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT: "/label-studio/data"

volumes:
  - name: data
    path: /label-studio/data
    size: 2g

command: ["label-studio", "start", "--no-browser",
          "--username", "demo@demoforge.local",
          "--password", "DemoForge123!"]

health_check:
  endpoint: /health
  port: 8080
  interval: 15s
  timeout: 10s
  start_period: "30s"

secrets:
  - key: LABEL_STUDIO_USERNAME
    label: "Admin Email"
    default: "demo@demoforge.local"
  - key: LABEL_STUDIO_PASSWORD
    label: "Admin Password"
    default: "DemoForge123!"

web_ui:
  - name: app
    port: 8080
    path: /
    description: "Label Studio — data annotation, project management, labeling interface"

terminal:
  shell: /bin/bash
  welcome_message: "Label Studio container."
  quick_actions:
    - label: "Health check"
      command: "curl -s http://localhost:8080/health || echo 'Not ready'"
    - label: "List projects"
      command: "curl -s -H 'Authorization: Token $LABEL_STUDIO_USER_TOKEN' http://localhost:8080/api/projects/ 2>/dev/null | python3 -m json.tool || echo 'Not ready'"

connections:
  provides:
    - type: labeling-api
      port: 8080
      description: "Label Studio API — project management, data import/export"
  accepts:
    - type: s3
      config_schema:
        - key: source_bucket
          label: "Source Data Bucket"
          type: string
          default: "labeling-data"
          description: "MinIO bucket containing data to label (images, text, audio)"
        - key: output_bucket
          label: "Labeled Output Bucket"
          type: string
          default: "labeled-output"
          description: "MinIO bucket for exported annotations"

variants:
  default:
    description: "SQLite backend (single-user, simple)"
  with-postgres:
    description: "PostgreSQL backend (multi-user, production-like)"

template_mounts: []
static_mounts: []
init_scripts: []
```

### 1.4 Milvus — `components/milvus/manifest.yaml`

```yaml
id: milvus
name: Milvus
category: database
icon: milvus
version: "latest"
image: milvusdb/milvus:v2.4-latest
description: "Enterprise vector database — uses MinIO as primary storage backend"

resources:
  memory: "2g"
  cpu: 1.0

ports:
  - name: grpc
    container: 19530
    protocol: tcp
  - name: http
    container: 9091
    protocol: tcp

environment:
  ETCD_ENDPOINTS: ""
  MINIO_ADDRESS: ""
  MINIO_PORT: "9000"
  MINIO_ACCESS_KEY: "minioadmin"
  MINIO_SECRET_KEY: "minioadmin"
  MINIO_USE_SSL: "false"
  MINIO_BUCKET_NAME: "milvus-data"

volumes:
  - name: data
    path: /var/lib/milvus
    size: 5g

command: ["milvus", "run", "standalone"]

health_check:
  endpoint: /healthz
  port: 9091
  interval: 15s
  timeout: 10s
  start_period: "45s"

secrets:
  - key: MINIO_ACCESS_KEY
    label: "MinIO Access Key"
    default: "minioadmin"
  - key: MINIO_SECRET_KEY
    label: "MinIO Secret Key"
    default: "minioadmin"

web_ui:
  - name: api
    port: 9091
    path: /
    description: "Milvus HTTP API — health, metrics"

terminal:
  shell: /bin/sh
  welcome_message: "Milvus vector database. Storage backend: MinIO."
  quick_actions:
    - label: "Health check"
      command: "wget -qO- http://localhost:9091/healthz 2>/dev/null || echo 'Not ready'"
    - label: "Check metrics"
      command: "wget -qO- http://localhost:9091/metrics 2>/dev/null | head -20"

connections:
  provides:
    - type: vector-db-milvus
      port: 19530
      description: "Milvus gRPC API for vector operations"
  accepts:
    - type: s3
      config_schema:
        - key: milvus_bucket
          label: "Milvus Data Bucket"
          type: string
          default: "milvus-data"
          description: "MinIO bucket for Milvus primary storage (segments, indexes, logs)"

variants:
  standalone:
    description: "Standalone mode with embedded etcd"
    command: ["milvus", "run", "standalone"]

template_mounts: []
static_mounts: []

init_scripts:
  - command: "sh -c 'until wget -qO- http://localhost:9091/healthz 2>/dev/null | grep -q ok; do sleep 5; done; echo Milvus ready'"
    wait_for_healthy: true
    timeout: 120
    order: 1
    description: "Wait for Milvus to fully initialize"
```

**Milvus also needs etcd** — create `components/etcd/manifest.yaml`:

```yaml
id: etcd
name: etcd
category: infrastructure
icon: etcd
version: "latest"
image: quay.io/coreos/etcd:v3.5.16
description: "Distributed key-value store (required by Milvus)"

resources:
  memory: "256m"
  cpu: 0.25

ports:
  - name: client
    container: 2379
    protocol: tcp

environment:
  ETCD_AUTO_COMPACTION_MODE: "revision"
  ETCD_AUTO_COMPACTION_RETENTION: "1000"
  ETCD_QUOTA_BACKEND_BYTES: "4294967296"
  ETCD_SNAPSHOT_COUNT: "50000"

volumes:
  - name: data
    path: /etcd
    size: 1g

command: ["etcd",
          "-advertise-client-urls=http://127.0.0.1:2379",
          "-listen-client-urls=http://0.0.0.0:2379",
          "--data-dir=/etcd",
          "--initial-advertise-peer-urls=http://127.0.0.1:2380",
          "-listen-peer-urls=http://0.0.0.0:2380",
          "--initial-cluster=default=http://127.0.0.1:2380"]

health_check:
  endpoint: /health
  port: 2379
  interval: 10s
  timeout: 5s
  start_period: "10s"

secrets: []
web_ui: []

terminal:
  shell: /bin/sh
  welcome_message: "etcd container."
  quick_actions:
    - label: "Health check"
      command: "wget -qO- http://localhost:2379/health 2>/dev/null || echo 'Not ready'"

connections:
  provides:
    - type: etcd
      port: 2379
      description: "etcd client endpoint"
  accepts: []

variants:
  default:
    description: "Single-node etcd"

template_mounts: []
static_mounts: []
init_scripts: []
```

### 1.5 Apache Airflow — `components/airflow/manifest.yaml`

```yaml
id: airflow
name: Apache Airflow
category: ai
icon: airflow
version: "latest"
image: apache/airflow:2.10.4-python3.12
description: "Workflow orchestration for ML and data pipelines"

resources:
  memory: "1g"
  cpu: 0.5

ports:
  - name: web
    container: 8080
    protocol: tcp

environment:
  AIRFLOW__CORE__EXECUTOR: "SequentialExecutor"
  AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: "sqlite:////opt/airflow/airflow.db"
  AIRFLOW__CORE__FERNET_KEY: ""
  AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "false"
  AIRFLOW__CORE__LOAD_EXAMPLES: "false"
  AIRFLOW__WEBSERVER__EXPOSE_CONFIG: "true"
  AIRFLOW_CONN_MINIO_S3: ""
  _AIRFLOW_DB_MIGRATE: "true"
  _AIRFLOW_WWW_USER_CREATE: "true"
  _AIRFLOW_WWW_USER_USERNAME: "admin"
  _AIRFLOW_WWW_USER_PASSWORD: "demoforge"

volumes:
  - name: dags
    path: /opt/airflow/dags
    size: 1g
  - name: logs
    path: /opt/airflow/logs
    size: 1g

command: ["bash", "-c", "airflow db migrate && airflow users create --username admin --password demoforge --firstname Demo --lastname Forge --role Admin --email admin@demoforge.local 2>/dev/null; airflow webserver --port 8080 & airflow scheduler & wait"]

health_check:
  endpoint: /health
  port: 8080
  interval: 15s
  timeout: 10s
  start_period: "45s"

secrets:
  - key: _AIRFLOW_WWW_USER_PASSWORD
    label: "Admin Password"
    default: "demoforge"

web_ui:
  - name: dashboard
    port: 8080
    path: /
    description: "Airflow UI — DAG management, run history, task logs"

terminal:
  shell: /bin/bash
  welcome_message: "Apache Airflow container."
  quick_actions:
    - label: "List DAGs"
      command: "airflow dags list 2>/dev/null || echo 'Not ready'"
    - label: "Check scheduler"
      command: "airflow jobs check --hostname $(hostname) 2>/dev/null || echo 'Scheduler not running'"

connections:
  provides:
    - type: workflow-api
      port: 8080
      description: "Airflow REST API — trigger DAGs, check status"
  accepts:
    - type: s3
      config_schema:
        - key: dag_bucket
          label: "DAG Storage Bucket"
          type: string
          default: "airflow-dags"
        - key: log_bucket
          label: "Log Storage Bucket"
          type: string
          default: "airflow-logs"

variants:
  default:
    description: "Standalone with SequentialExecutor and SQLite"

template_mounts: []
static_mounts: []
init_scripts: []
```

### 1.6 LiteLLM — `components/litellm/manifest.yaml`

```yaml
id: litellm
name: LiteLLM
category: ai
icon: litellm
version: "latest"
image: ghcr.io/berriai/litellm:main-latest
description: "LLM gateway/proxy — unified API for multiple models with logging"

resources:
  memory: "256m"
  cpu: 0.25

ports:
  - name: api
    container: 4000
    protocol: tcp

environment:
  LITELLM_LOG: "DEBUG"
  STORE_MODEL_IN_DB: "false"

volumes: []

command: ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]

health_check:
  endpoint: /health/liveliness
  port: 4000
  interval: 10s
  timeout: 5s
  start_period: "15s"

secrets: []

web_ui:
  - name: api
    port: 4000
    path: /
    description: "LiteLLM proxy — OpenAI-compatible API"

terminal:
  shell: /bin/sh
  welcome_message: "LiteLLM proxy container."
  quick_actions:
    - label: "Health check"
      command: "wget -qO- http://localhost:4000/health/liveliness 2>/dev/null || echo 'Not ready'"
    - label: "List models"
      command: "wget -qO- http://localhost:4000/v1/models 2>/dev/null | head -50"

connections:
  provides:
    - type: llm-gateway
      port: 4000
      description: "OpenAI-compatible API gateway"
  accepts:
    - type: llm-api
      config_schema:
        - key: model_alias
          label: "Model Alias"
          type: string
          default: "gpt-3.5-turbo"
          description: "Name clients use to request this model"

variants:
  default:
    description: "Single-model proxy (routes to Ollama)"

template_mounts:
  - template: litellm-config.yaml.j2
    mount_path: /app/config.yaml

static_mounts: []
init_scripts: []
```

**Template** — `components/litellm/templates/litellm-config.yaml.j2`:

```yaml
model_list:
{% for edge in edges %}
{% if edge.connection_type == 'llm-api' and edge.source == node.id %}
  - model_name: "{{ edge.connection_config.get('model_alias', 'default') }}"
    litellm_params:
      model: "ollama/llama3.2:3b"
      api_base: "http://{{ project_name }}-{{ edge.target }}:11434"
{% endif %}
{% endfor %}

general_settings:
  master_key: "sk-demoforge"

litellm_settings:
  success_callback: ["custom_callback"]
  cache: false
```

### 1.7 ML Trainer — `components/ml-trainer/manifest.yaml`

A custom container that runs actual scikit-learn experiments and logs to MLflow. Not a simulator — real training on real data from MinIO.

```yaml
id: ml-trainer
name: ML Trainer
category: ai
icon: ml-trainer
version: "1.0"
image: demoforge/ml-trainer:latest
build_context: "."
description: "Runs ML training experiments on MinIO data, logs to MLflow"

resources:
  memory: "512m"
  cpu: 0.5

ports:
  - name: api
    container: 8090
    protocol: tcp

environment:
  MINIO_ENDPOINT: ""
  MINIO_ACCESS_KEY: "minioadmin"
  MINIO_SECRET_KEY: "minioadmin"
  MLFLOW_TRACKING_URI: ""
  MLFLOW_S3_ENDPOINT_URL: ""
  AWS_ACCESS_KEY_ID: "minioadmin"
  AWS_SECRET_ACCESS_KEY: "minioadmin"
  TRAINING_BUCKET: "training-data"
  MODEL_BUCKET: "models"
  EXPERIMENT_NAME: "demoforge-experiment"

volumes: []

command: []

health_check:
  endpoint: /health
  port: 8090
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
  - name: dashboard
    port: 8090
    path: /
    description: "Training dashboard — run status, metrics"

terminal:
  shell: /bin/bash
  welcome_message: "ML Trainer container."
  quick_actions:
    - label: "Run quick training"
      command: "wget -qO- --post-data='{\"n_runs\": 3}' --header='Content-Type: application/json' http://localhost:8090/train/quick 2>/dev/null || echo 'Not ready'"
    - label: "Check status"
      command: "wget -qO- http://localhost:8090/status 2>/dev/null || echo 'Not ready'"

connections:
  provides: []
  accepts:
    - type: s3
      config_schema:
        - key: training_bucket
          label: "Training Data Bucket"
          type: string
          default: "training-data"
    - type: mlflow-tracking
      config_schema: []

variants:
  default:
    description: "Scikit-learn trainer with MLflow logging"

template_mounts: []
static_mounts: []
init_scripts: []
```

**Build `components/ml-trainer/`**:

The ml-trainer is a FastAPI app that:

- `POST /train/quick` — runs 3-5 sklearn experiments (RandomForest, GradientBoosting, LinearRegression) with different hyperparameters on data from the MinIO training bucket. Logs everything to MLflow: params, metrics per step, model pickle, confusion matrix PNG, feature importance chart.
- `POST /train/sweep` — runs 10-20 hyperparameter variations, finds the best, promotes it in the MLflow model registry.
- `GET /status` — current training state, last run info.
- `POST /prepare-data` — reads raw ecommerce-orders data from the data-generator's bucket, does train/test split, writes to training-data bucket. This bridges the data-generator to the trainer.

The training is real — actual sklearn models on actual Parquet data from MinIO. Not fake metrics. The audience can click into MLflow and see real learning curves, real confusion matrices, real model files.

---

## Part 2: New connection types in compose generator

File: `backend/app/engine/compose_generator.py`

Add these to the edge resolution loop:

```python
# MLflow tracking
if edge.connection_type == "mlflow-tracking":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        mlflow_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 5000)
        env["MLFLOW_TRACKING_URI"] = f"http://{project_name}-{peer_id}:{mlflow_port}"
        # Also set S3 endpoint for artifact access (MLflow needs this on the client side)
        env["MLFLOW_S3_ENDPOINT_URL"] = env.get("MINIO_ENDPOINT", env.get("S3_ENDPOINT", ""))

# Milvus S3 storage
if edge.connection_type == "s3" and node_component == "milvus":
    env["MINIO_ADDRESS"] = f"{project_name}-{peer_id}"
    env["MINIO_PORT"] = "9000"
    edge_cfg = edge.connection_config or {}
    env["MINIO_BUCKET_NAME"] = edge_cfg.get("milvus_bucket", "milvus-data")

# etcd for Milvus
if edge.connection_type == "etcd":
    env["ETCD_ENDPOINTS"] = f"{project_name}-{peer_id}:2379"

# Workflow API (Airflow)
if edge.connection_type == "workflow-api":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        airflow_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 8080)
        env["AIRFLOW_API_URL"] = f"http://{project_name}-{peer_id}:{airflow_port}"

# LLM gateway (LiteLLM)
if edge.connection_type == "llm-gateway":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        gw_port = next((p.container for p in peer_manifest.ports if p.name == "api"), 4000)
        env["LLM_GATEWAY_URL"] = f"http://{project_name}-{peer_id}:{gw_port}"
        env["OPENAI_API_BASE"] = f"http://{project_name}-{peer_id}:{gw_port}/v1"

# Labeling API
if edge.connection_type == "labeling-api":
    peer_manifest = get_component(peer_component)
    if peer_manifest:
        ls_port = next((p.container for p in peer_manifest.ports if p.name == "web"), 8080)
        env["LABEL_STUDIO_URL"] = f"http://{project_name}-{peer_id}:{ls_port}"
```

Add to `_edge_env_map`:

```python
"artifact_bucket": "MLFLOW_ARTIFACTS_BUCKET",
"source_bucket": "LABELING_SOURCE_BUCKET",
"output_bucket": "LABELING_OUTPUT_BUCKET",
"milvus_bucket": "MINIO_BUCKET_NAME",
"training_bucket": "TRAINING_BUCKET",
"dag_bucket": "AIRFLOW_DAG_BUCKET",
"log_bucket": "AIRFLOW_LOG_BUCKET",
```

File: `frontend/src/types/index.ts` — add to `ConnectionType`:

```typescript
| "mlflow-tracking" | "vector-db-milvus" | "etcd" | "labeling-api" | "workflow-api" | "llm-gateway"
```

---

## Part 3: Data generation extensions

The existing data-generator already produces ecommerce-orders, iot-telemetry, and financial-txn. For the AI demos, we need two additional dataset scenarios that generate data suitable for labeling and ML training.

### 3.1 New scenario: `datasets/text-classification.yaml`

For Label Studio text labeling demos:

```yaml
id: text-classification
name: "Text classification corpus"
description: "Support tickets with category labels. Designed for Label Studio annotation demos."

schema:
  columns:
    - name: ticket_id
      type: string
      generator: uuid

    - name: created_at
      type: timestamp
      generator: now_jitter

    - name: subject
      type: string
      generator:
        type: template
        templates:
          - "Issue with {product} - {problem}"
          - "{product} not working after {event}"
          - "Request: {action} for {product}"
          - "Help needed: {problem} with {product}"
        variables:
          product: ["Cloud Storage", "API Gateway", "Dashboard", "Billing Portal", "Mobile App"]
          problem: ["login failure", "slow performance", "data sync error", "timeout", "permission denied"]
          event: ["update", "migration", "password reset", "config change"]
          action: ["upgrade", "refund", "access grant", "feature request", "account merge"]

    - name: body
      type: string
      generator:
        type: fake_paragraph
        sentences: {min: 3, max: 8}

    - name: priority
      type: string
      generator:
        type: weighted_enum
        values:
          "low": 0.40
          "medium": 0.35
          "high": 0.20
          "critical": 0.05

    - name: true_category
      type: string
      generator:
        type: weighted_enum
        values:
          "technical_issue": 0.35
          "billing": 0.20
          "feature_request": 0.15
          "account_access": 0.15
          "general_inquiry": 0.15

    - name: sentiment
      type: string
      generator:
        type: weighted_enum
        values:
          "frustrated": 0.30
          "neutral": 0.45
          "polite": 0.20
          "angry": 0.05

partitioning:
  parquet:
    keys: [true_category]
    time_column: created_at
    time_granularity: day
  json: flat
  csv: flat

buckets:
  parquet: "support-tickets-parquet"
  json: "support-tickets-json"
  csv: "support-tickets-csv"

volume:
  default_rows_per_batch: 100
  default_batches_per_minute: 4
  profiles:
    low:    {rows_per_batch: 20, batches_per_minute: 2}
    medium: {rows_per_batch: 100, batches_per_minute: 4}
    high:   {rows_per_batch: 500, batches_per_minute: 10}
  ramp_up_seconds: 10

queries:
  - id: category_distribution
    name: "Category distribution"
    sql: >
      SELECT true_category, COUNT(*) AS count
      FROM {catalog}.{namespace}.support_tickets
      GROUP BY true_category
      ORDER BY count DESC
    chart_type: bar

  - id: priority_breakdown
    name: "Priority breakdown"
    sql: >
      SELECT priority, COUNT(*) AS count
      FROM {catalog}.{namespace}.support_tickets
      GROUP BY priority
    chart_type: donut

  - id: tickets_per_minute
    name: "Tickets per minute"
    sql: >
      SELECT date_trunc('minute', created_at) AS minute,
             COUNT(*) AS tickets
      FROM {catalog}.{namespace}.support_tickets
      WHERE created_at > current_timestamp - interval '30' minute
      GROUP BY 1 ORDER BY 1
    chart_type: line
    auto_refresh_seconds: 10

metabase_dashboard:
  name: "Support Tickets"
  description: "Real-time support ticket monitoring"
  layout:
    - {query: tickets_per_minute, row: 0, col: 0, width: 12, height: 5}
    - {query: category_distribution, row: 0, col: 12, width: 6, height: 5}
    - {query: priority_breakdown, row: 5, col: 0, width: 6, height: 5}
```

### 3.2 New scenario: `datasets/image-metadata.yaml`

For Label Studio image labeling demos (generates metadata + placeholder images):

```yaml
id: image-metadata
name: "Image classification metadata"
description: "Product image metadata with categories. Generates small placeholder images + metadata CSV for labeling."

schema:
  columns:
    - name: image_id
      type: string
      generator: uuid

    - name: filename
      type: string
      generator: {type: computed, expression: "'img_' + image_id[:8] + '.jpg'"}

    - name: upload_ts
      type: timestamp
      generator: now_jitter

    - name: product_category
      type: string
      generator:
        type: weighted_enum
        values:
          "electronics": 0.25
          "clothing": 0.20
          "furniture": 0.15
          "food_beverage": 0.15
          "automotive": 0.10
          "sports": 0.10
          "other": 0.05

    - name: width
      type: int32
      generator: {type: enum, values: [640, 800, 1024, 1280]}

    - name: height
      type: int32
      generator: {type: enum, values: [480, 600, 768, 960]}

    - name: file_size_kb
      type: int32
      generator: {type: range, min: 50, max: 2000}

    - name: needs_review
      type: boolean
      generator: {type: weighted_bool, true_pct: 0.30}

buckets:
  parquet: "image-catalog"
  json: "image-catalog-json"
  csv: "image-catalog-csv"

volume:
  default_rows_per_batch: 50
  default_batches_per_minute: 2
  profiles:
    low:    {rows_per_batch: 10, batches_per_minute: 1}
    medium: {rows_per_batch: 50, batches_per_minute: 2}
    high:   {rows_per_batch: 200, batches_per_minute: 5}
```

For image labeling demos, also generate small placeholder images (colored rectangles with text) and upload them to the labeling bucket. The data-generator should have a mode where it generates both the metadata CSV/Parquet AND the placeholder images in MinIO. This way Label Studio can actually display images from the bucket.

---

## Part 4: Demo Templates

### Template 1: "ML Experiment Lab"

The flagship ML demo. Data flows from MinIO into JupyterLab and MLflow for training and tracking.

```yaml
_template:
  name: "ML Experiment Lab"
  category: "ai"
  tags: ["mlflow", "jupyter", "training", "experiment-tracking", "sklearn"]
  description: "Train ML models on MinIO data, track experiments in MLflow, browse artifacts. JupyterLab for interactive exploration."
  objective: "Demonstrate MinIO as the artifact store and data lake for the ML lifecycle"
  minio_value: "MLflow stores all model artifacts, training plots, and evaluation datasets in MinIO. JupyterLab reads training data from MinIO. The entire ML lifecycle runs on one storage platform."
  estimated_resources:
    memory: "4GB"
    cpu: 3
    containers: 5
  walkthrough:
    - step: "Deploy and generate data"
      description: "Click Deploy. Start the data generator with E-commerce orders scenario to populate MinIO with training data."
    - step: "Prepare training data"
      description: "Open ML Trainer → click 'Prepare data' to split raw data into train/test sets in MinIO."
    - step: "Run training experiments"
      description: "Click 'Run quick training' — 3 different models train on MinIO data, log to MLflow."
    - step: "Compare in MLflow"
      description: "Open MLflow UI → compare runs → click the best model → browse artifacts (stored in MinIO)."
    - step: "Explore in JupyterLab"
      description: "Open JupyterLab → run notebook 03 → see real training with mlflow.log_model()."
    - step: "Check MinIO"
      description: "Open MinIO Console → mlflow-artifacts bucket → model files, plots, metrics all stored as objects."
  external_dependencies: []

id: template-ml-experiment-lab
name: "ML Experiment Lab"
description: "Train models on MinIO data, track in MLflow, explore in JupyterLab"

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

  - id: data-gen
    component: data-generator
    variant: default
    position: {x: -200, y: 250}
    display_name: "Data Generator"

  - id: mlflow-1
    component: mlflow
    variant: default
    position: {x: 400, y: 100}
    display_name: "MLflow"

  - id: jupyter-1
    component: jupyterlab
    variant: default
    position: {x: 400, y: 400}
    display_name: "JupyterLab"

  - id: trainer-1
    component: ml-trainer
    variant: default
    position: {x: 700, y: 250}
    display_name: "ML Trainer"

clusters: []

edges:
  - id: e-datagen-minio
    source: data-gen
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Raw data"
    connection_config:
      bucket: "raw-data"
      format: "parquet"
      scenario: "ecommerce-orders"

  - id: e-mlflow-minio
    source: mlflow-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Model artifacts"
    connection_config:
      artifact_bucket: "mlflow-artifacts"

  - id: e-jupyter-minio
    source: jupyter-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Read/write data"

  - id: e-jupyter-mlflow
    source: jupyter-1
    target: mlflow-1
    connection_type: mlflow-tracking
    auto_configure: true
    label: "Log experiments"

  - id: e-trainer-minio
    source: trainer-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Training data"
    connection_config:
      training_bucket: "training-data"

  - id: e-trainer-mlflow
    source: trainer-1
    target: mlflow-1
    connection_type: mlflow-tracking
    auto_configure: true
    label: "Track experiments"

groups: []
sticky_notes: []

resources:
  default_memory: "512m"
  default_cpu: 0.5
  total_memory: "6g"
  total_cpu: 4.0
```

### Template 2: "AI Data Labeling Pipeline"

End-to-end: data arrives in MinIO → Label Studio annotates it → labeled data goes back to MinIO → train on it.

```yaml
_template:
  name: "AI Data Labeling Pipeline"
  category: "ai"
  tags: ["label-studio", "labeling", "annotation", "training-data"]
  description: "Generate data into MinIO, label it in Label Studio, export annotations back to MinIO, train on labeled data."
  objective: "Demonstrate MinIO as the data backbone for AI data preparation"
  minio_value: "Raw data, labeled annotations, and trained models all live in MinIO. Label Studio reads directly from and writes to MinIO buckets. No data ever leaves your infrastructure."
  estimated_resources:
    memory: "3GB"
    cpu: 2
    containers: 4
  walkthrough:
    - step: "Deploy and generate data"
      description: "Deploy the demo. Start data generator with 'Text classification' scenario."
    - step: "Open Label Studio"
      description: "Open Label Studio UI. Create a project for text classification."
    - step: "Connect MinIO as source"
      description: "Add S3 storage source pointing to the support-tickets bucket in MinIO."
    - step: "Label some tickets"
      description: "Annotate 10-20 support tickets with categories. Label Studio reads from MinIO."
    - step: "Export annotations"
      description: "Export labeled data back to the output bucket in MinIO."
    - step: "Verify in MinIO"
      description: "Open MinIO Console — see raw data in source bucket, annotations in output bucket."
  external_dependencies: []

id: template-data-labeling-pipeline
name: "AI Data Labeling Pipeline"
description: "Generate → Label in Label Studio → Export to MinIO → all data stays on your infrastructure"

networks:
  - name: default
    subnet: 172.20.0.0/16
    driver: bridge

nodes:
  - id: minio-1
    component: minio
    variant: single
    position: {x: 250, y: 250}
    display_name: "MinIO"

  - id: data-gen
    component: data-generator
    variant: default
    position: {x: -100, y: 250}
    display_name: "Data Generator"
    config:
      DG_SCENARIO: "text-classification"
      DG_FORMAT: "json"

  - id: label-studio-1
    component: label-studio
    variant: default
    position: {x: 600, y: 100}
    display_name: "Label Studio"

  - id: jupyter-1
    component: jupyterlab
    variant: default
    position: {x: 600, y: 400}
    display_name: "JupyterLab"

clusters: []

edges:
  - id: e-datagen-minio
    source: data-gen
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Support tickets"
    connection_config:
      bucket: "labeling-data"
      format: "json"

  - id: e-label-minio
    source: label-studio-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Read data + write labels"
    connection_config:
      source_bucket: "labeling-data"
      output_bucket: "labeled-output"

  - id: e-jupyter-minio
    source: jupyter-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Train on labeled data"

groups: []
sticky_notes: []

resources:
  default_memory: "512m"
  default_cpu: 0.5
  total_memory: "4g"
  total_cpu: 3.0
```

### Template 3: "Enterprise Vector Search (Milvus)"

Shows Milvus using MinIO as its primary storage — not just a backing store, THE storage.

```yaml
_template:
  name: "Enterprise Vector Search"
  category: "ai"
  tags: ["milvus", "vector-db", "embeddings", "rag", "search"]
  description: "Milvus vector database with MinIO as primary storage. All vectors, indexes, and WAL segments live in MinIO."
  objective: "Demonstrate MinIO as the persistence layer for enterprise-scale vector search"
  minio_value: "Milvus doesn't manage its own storage — MinIO handles all persistence. Vectors, indexes, and logs are MinIO objects. Your embeddings get the same durability, replication, and encryption as the rest of your data."
  estimated_resources:
    memory: "5GB"
    cpu: 3
    containers: 5
  walkthrough:
    - step: "Deploy"
      description: "Click Deploy. Milvus takes ~30s to initialize with MinIO as its backend."
    - step: "Check MinIO"
      description: "Open MinIO Console → milvus-data bucket appears automatically. This is where Milvus stores everything."
    - step: "Ingest documents"
      description: "Start the data generator, then use the RAG app to ingest and embed sample documents."
    - step: "Query vectors"
      description: "Ask questions in the RAG chat UI — Milvus handles the vector search, backed by MinIO."
    - step: "Inspect storage"
      description: "Open MinIO Console → browse the milvus-data bucket → see segment files, index files, and WAL logs."
  external_dependencies: []

id: template-enterprise-vector-search
name: "Enterprise Vector Search (Milvus)"
description: "Milvus vector database with MinIO as primary storage backend"

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

  - id: etcd-1
    component: etcd
    variant: default
    position: {x: 350, y: 450}
    display_name: "etcd"

  - id: milvus-1
    component: milvus
    variant: standalone
    position: {x: 400, y: 250}
    display_name: "Milvus"

  - id: ollama-1
    component: ollama
    variant: default
    position: {x: 650, y: 100}
    display_name: "Ollama"

  - id: rag-1
    component: rag-app
    variant: default
    position: {x: 700, y: 350}
    display_name: "RAG Pipeline"
    config:
      QDRANT_ENDPOINT: ""
      VECTOR_DB_TYPE: "milvus"

clusters: []

edges:
  - id: e-milvus-minio
    source: milvus-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Primary storage"
    connection_config:
      milvus_bucket: "milvus-data"

  - id: e-milvus-etcd
    source: milvus-1
    target: etcd-1
    connection_type: etcd
    auto_configure: true
    label: "Metadata"

  - id: e-rag-milvus
    source: rag-1
    target: milvus-1
    connection_type: vector-db-milvus
    auto_configure: true
    label: "Vector search"

  - id: e-rag-ollama
    source: rag-1
    target: ollama-1
    connection_type: llm-api
    auto_configure: true
    label: "Embed + generate"

  - id: e-rag-minio
    source: rag-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Docs + audit"

groups: []
sticky_notes: []

resources:
  default_memory: "512m"
  default_cpu: 0.5
  total_memory: "8g"
  total_cpu: 4.0
```

**Note:** The rag-app needs a small update to support Milvus as an alternative to Qdrant. Add a `VECTOR_DB_TYPE` env var (`qdrant` or `milvus`, default `qdrant`). When `milvus`, use `pymilvus` instead of `qdrant_client`. Same pipeline logic, different vector store client.

### Template 4: "Automated ML Pipeline"

Airflow orchestrates the full flow: generate data → prepare features → train → evaluate → register model.

```yaml
_template:
  name: "Automated ML Pipeline"
  category: "ai"
  tags: ["airflow", "mlflow", "pipeline", "mlops", "automation"]
  description: "Airflow orchestrates end-to-end ML: data generation → feature engineering → model training → MLflow registration. All data in MinIO."
  objective: "Demonstrate MinIO as the backbone of an automated MLOps pipeline"
  minio_value: "Every stage reads from and writes to MinIO — raw data, feature sets, model artifacts, pipeline logs. Airflow DAGs trigger the flow, MinIO holds the data."
  estimated_resources:
    memory: "5GB"
    cpu: 3
    containers: 5
  walkthrough:
    - step: "Deploy"
      description: "Click Deploy. Airflow initializes with pre-loaded DAGs."
    - step: "Start data flow"
      description: "Start the data generator. Raw data flows into MinIO."
    - step: "Trigger the pipeline"
      description: "Open Airflow UI → trigger the 'ml_training_pipeline' DAG."
    - step: "Watch it run"
      description: "The DAG reads data from MinIO, trains models, logs to MLflow — all automated."
    - step: "Check results"
      description: "Open MLflow — trained model registered. Open MinIO — artifacts stored."
  external_dependencies: []

id: template-automated-ml-pipeline
name: "Automated ML Pipeline"
description: "Airflow-orchestrated ML pipeline: data → features → training → MLflow. All data in MinIO."

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

  - id: data-gen
    component: data-generator
    variant: default
    position: {x: -200, y: 250}
    display_name: "Data Generator"

  - id: airflow-1
    component: airflow
    variant: default
    position: {x: 400, y: 100}
    display_name: "Airflow"

  - id: mlflow-1
    component: mlflow
    variant: default
    position: {x: 700, y: 100}
    display_name: "MLflow"

  - id: trainer-1
    component: ml-trainer
    variant: default
    position: {x: 700, y: 400}
    display_name: "ML Trainer"

clusters: []

edges:
  - id: e-datagen-minio
    source: data-gen
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Raw data"
    connection_config:
      bucket: "raw-data"

  - id: e-airflow-minio
    source: airflow-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "DAGs + logs"

  - id: e-airflow-trainer
    source: airflow-1
    target: trainer-1
    connection_type: workflow-api
    auto_configure: true
    label: "Trigger training"

  - id: e-trainer-minio
    source: trainer-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Training data"

  - id: e-trainer-mlflow
    source: trainer-1
    target: mlflow-1
    connection_type: mlflow-tracking
    auto_configure: true
    label: "Log experiments"

  - id: e-mlflow-minio
    source: mlflow-1
    target: minio-1
    connection_type: s3
    auto_configure: true
    label: "Model artifacts"

groups: []
sticky_notes: []

resources:
  default_memory: "512m"
  default_cpu: 0.5
  total_memory: "8g"
  total_cpu: 4.0
```

**Pre-loaded Airflow DAG** — create `components/airflow/dags/ml_training_pipeline.py`:

A DAG that:
1. `check_data` — verifies raw data exists in MinIO (S3 sensor)
2. `prepare_features` — calls ML Trainer's `/prepare-data` endpoint
3. `train_model` — calls ML Trainer's `/train/quick` endpoint
4. `register_best` — calls ML Trainer's `/train/sweep` endpoint (finds and registers best model)

Mount this DAG into the Airflow container via `static_mounts` or `template_mounts`.

### Template 5: "MinIO AI Platform" (combined)

The ultimate demo — combines everything into one topology. Only build this after Templates 1-4 work individually.

```yaml
_template:
  name: "MinIO AI Platform"
  category: "ai"
  tags: ["platform", "full-stack", "rag", "mlflow", "jupyter", "label-studio", "milvus"]
  description: "The complete AI data platform: labeling, training, experiment tracking, vector search, RAG — all on MinIO."
  objective: "Show MinIO as the single data foundation for the entire AI lifecycle"
  minio_value: "One storage platform for: raw data, labeled datasets, training artifacts, model weights, vector embeddings, inference logs, and audit trails."
  estimated_resources:
    memory: "12GB"
    cpu: 8
    containers: 10
  walkthrough:
    - step: "Deploy the platform"
      description: "Click Deploy. 10 containers start — all connected through MinIO."
    - step: "Data ingestion"
      description: "Start Data Generator → raw data flows into MinIO."
    - step: "Label data"
      description: "Open Label Studio → annotate support tickets from MinIO."
    - step: "Train models"
      description: "Open JupyterLab → run training notebook → logs to MLflow, artifacts in MinIO."
    - step: "Build knowledge base"
      description: "Upload documents to MinIO → RAG pipeline embeds them → Milvus stores vectors in MinIO."
    - step: "Ask questions"
      description: "Chat UI → ask about your documents → grounded answers with citations."
    - step: "View everything in MinIO"
      description: "Open MinIO Console → every bucket tells a story: raw-data, labeled-output, mlflow-artifacts, milvus-data, documents, rag-audit-log."
  external_dependencies:
    - "Ollama model download requires internet on first deploy (~1.8GB)"

id: template-minio-ai-platform
name: "MinIO AI Platform"
description: "Complete AI lifecycle on MinIO: label → train → track → embed → query → audit"

networks:
  - name: default
    subnet: 172.20.0.0/16
    driver: bridge

nodes:
  - id: minio-1
    component: minio
    variant: single
    position: {x: 400, y: 300}
    display_name: "MinIO AIStor"

  - id: data-gen
    component: data-generator
    variant: default
    position: {x: 50, y: 300}
    display_name: "Data Generator"

  - id: label-studio-1
    component: label-studio
    variant: default
    position: {x: 100, y: 50}
    display_name: "Label Studio"

  - id: jupyter-1
    component: jupyterlab
    variant: default
    position: {x: 100, y: 550}
    display_name: "JupyterLab"

  - id: mlflow-1
    component: mlflow
    variant: default
    position: {x: 400, y: 50}
    display_name: "MLflow"

  - id: trainer-1
    component: ml-trainer
    variant: default
    position: {x: 400, y: 550}
    display_name: "ML Trainer"

  - id: etcd-1
    component: etcd
    variant: default
    position: {x: 600, y: 550}
    display_name: "etcd"

  - id: milvus-1
    component: milvus
    variant: standalone
    position: {x: 700, y: 400}
    display_name: "Milvus"

  - id: ollama-1
    component: ollama
    variant: default
    position: {x: 700, y: 50}
    display_name: "Ollama"

  - id: rag-1
    component: rag-app
    variant: default
    position: {x: 900, y: 250}
    display_name: "RAG Pipeline"

clusters: []

edges:
  - {id: e1, source: data-gen, target: minio-1, connection_type: s3, auto_configure: true, label: "Raw data"}
  - {id: e2, source: label-studio-1, target: minio-1, connection_type: s3, auto_configure: true, label: "Label data"}
  - {id: e3, source: jupyter-1, target: minio-1, connection_type: s3, auto_configure: true, label: "Explore data"}
  - {id: e4, source: jupyter-1, target: mlflow-1, connection_type: mlflow-tracking, auto_configure: true, label: "Log experiments"}
  - {id: e5, source: mlflow-1, target: minio-1, connection_type: s3, auto_configure: true, label: "Artifacts"}
  - {id: e6, source: trainer-1, target: minio-1, connection_type: s3, auto_configure: true, label: "Training data"}
  - {id: e7, source: trainer-1, target: mlflow-1, connection_type: mlflow-tracking, auto_configure: true, label: "Track runs"}
  - {id: e8, source: milvus-1, target: minio-1, connection_type: s3, auto_configure: true, label: "Vector storage"}
  - {id: e9, source: milvus-1, target: etcd-1, connection_type: etcd, auto_configure: true, label: "Metadata"}
  - {id: e10, source: rag-1, target: milvus-1, connection_type: vector-db-milvus, auto_configure: true, label: "Vector search"}
  - {id: e11, source: rag-1, target: ollama-1, connection_type: llm-api, auto_configure: true, label: "Embed + generate"}
  - {id: e12, source: rag-1, target: minio-1, connection_type: s3, auto_configure: true, label: "Docs + audit"}

groups: []
sticky_notes: []

resources:
  default_memory: "512m"
  default_cpu: 0.5
  total_memory: "16g"
  total_cpu: 8.0
```

---

## Part 5: Build order

Build these in sequence. Each step should be deployable and testable before moving to the next.

**Phase 1: MLflow + JupyterLab + ML Trainer** (Template 1)
1. Create manifests for `mlflow`, `jupyterlab`, `ml-trainer`
2. Build JupyterLab custom image with pre-loaded notebooks
3. Build ML Trainer container (FastAPI, real sklearn training, MLflow logging)
4. Add `mlflow-tracking` edge resolution to compose generator
5. Create Template 1 and deploy

**Phase 2: Label Studio + text-classification scenario** (Template 2)
1. Create `label-studio` manifest
2. Add `text-classification` dataset scenario to data-generator
3. Add `labeling-api` edge resolution
4. Create Template 2 and deploy

**Phase 3: Milvus** (Template 3)
1. Create `milvus` and `etcd` manifests
2. Add `vector-db-milvus` and `etcd` edge resolution
3. Update rag-app to support Milvus as alternative vector store (via `VECTOR_DB_TYPE` env var)
4. Create Template 3 and deploy

**Phase 4: Airflow** (Template 4)
1. Create `airflow` manifest
2. Create pre-loaded DAG file for ML pipeline
3. Add `workflow-api` edge resolution
4. Create Template 4 and deploy

**Phase 5: LiteLLM + combined template** (Template 5)
1. Create `litellm` manifest with Jinja2 config template
2. Create the combined "MinIO AI Platform" template
3. Test with 12GB+ RAM available

---

## Verification for each phase

### Phase 1 verification
1. Deploy Template 1 → all 5 nodes green
2. Start data generator → ecommerce data flowing to MinIO
3. Open ML Trainer → click "Prepare data" → train/test split in MinIO
4. Click "Run quick training" → 3 experiments appear in MLflow
5. Open MLflow UI → compare runs → click best → Artifacts tab → model file loads from MinIO
6. Open JupyterLab → run notebook 03 → training logged to MLflow
7. Open MinIO Console → `mlflow-artifacts` bucket → model dirs with pickle files and PNGs

### Phase 2 verification
1. Deploy Template 2 → all 4 nodes green
2. Start data generator with text-classification scenario → JSON tickets in MinIO
3. Open Label Studio → create text classification project
4. Connect MinIO as S3 source → tickets appear
5. Label 5-10 tickets → export → labeled data in MinIO output bucket

### Phase 3 verification
1. Deploy Template 3 → all 5 nodes green (Milvus takes ~30s)
2. Check MinIO Console → `milvus-data` bucket exists with segment files
3. Load sample docs in RAG app → embeddings stored via Milvus → in MinIO
4. Ask question → grounded answer

### Phase 4 verification
1. Deploy Template 4 → all 5 nodes green
2. Start data generator → raw data in MinIO
3. Open Airflow UI → trigger `ml_training_pipeline` DAG
4. Watch tasks execute in sequence
5. Check MLflow → new experiment with runs from the Airflow-triggered training

---

## What NOT to do

- Don't build custom Docker images when the stock image works (MLflow, Label Studio, Airflow — use stock)
- Don't add GPU support — CPU inference everywhere
- Don't build Template 5 until Templates 1-4 work individually
- Don't modify the rag-app's core pipeline for Milvus — add it as an alternative backend behind an env var switch
- Don't add the `image-metadata` scenario until Label Studio is working with the text-classification scenario
- Don't create Airflow DAGs that call external APIs — everything should be internal to the demo network
- Don't install heavy ML frameworks (PyTorch, TensorFlow) in JupyterLab — scikit-learn is sufficient for the demo and keeps the image small
