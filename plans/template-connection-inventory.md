# DemoForge Template Connection Inventory

> Auto-generated from 26 templates, 177 total edges
> Last updated: scan of `demo-templates/*.yaml`

---

## Connection Type Registry

25 connection types across all templates:

| Connection Type | Count | Source Components | Target Components |
|----------------|-------|-------------------|-------------------|
| `cluster-replication` | 1 | minio | minio |
| `cluster-site-replication` | 4 | minio | minio |
| `dremio-sql` | 3 | metabase | dremio |
| `etcd` | 2 | milvus | etcd |
| `failover` | 2 | nginx | minio |
| `file-push` | 8 | file-generator | minio, nginx |
| `hdfs` | 2 | hdfs | spark |
| `iceberg-catalog` | 9 | dremio, iceberg-rest, trino | iceberg-rest, nessie, trino |
| `inference-api` | 1 | inference-client | inference-sim |
| `kafka` | 6 | data-generator, kafka-connect-s3, redpanda-console | redpanda |
| `llm-api` | 3 | rag-app | ollama |
| `load-balance` | 12 | nginx | minio |
| `metrics` | 31 | inference-sim, minio | prometheus |
| `metrics-query` | 13 | prometheus | grafana |
| `mlflow-tracking` | 5 | jupyterlab, ml-trainer | mlflow |
| `replication` | 3 | minio | minio |
| `s3` | 53 | airflow, data-generator, dremio, inference-sim, jupyterlab, kafka-connect-s3, label-studio, milvus, minio, minio-aistore, ml-trainer, mlflow, qdrant, rag-app, resilience-tester, trino | clickhouse, iceberg-rest, minio, minio-aistore, nginx, spark, trino |
| `schema-registry` | 2 | redpanda-console | redpanda |
| `site-replication` | 1 | minio | minio |
| `sql-query` | 8 | metabase, trino | metabase, trino |
| `structured-data` | 3 | data-generator | minio |
| `tiering` | 1 | minio | minio |
| `vector-db` | 1 | rag-app | qdrant |
| `vector-db-milvus` | 2 | rag-app | milvus |
| `workflow-api` | 1 | airflow | ml-trainer |

---

## Per-Template Edge Map

### Active-Active Replication

**File:** `active-active-replication.yaml` | **Nodes:** 5 | **Edges:** 7

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `nginx-lb` (nginx) → `minio-1` (minio) | `load-balance` | LB -> MinIO-1 | default → default | no |
| 2 | `nginx-lb` (nginx) → `minio-2` (minio) | `load-balance` | LB -> MinIO-2 | default → default | no |
| 3 | `minio-1` (minio) → `minio-2` (minio) | `replication` | Replication | default → default | no |
| 4 | `minio-2` (minio) → `minio-1` (minio) | `replication` | Replication | default → default | no |
| 5 | `minio-1` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | default → default | no |
| 6 | `minio-2` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | default → default | no |
| 7 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | no |

### Medallion Architecture

**File:** `experience-medallion.yaml` | **Nodes:** 5 | **Edges:** 4

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Raw data | default → default | yes |
| 2 | `minio-1` (minio) → `iceberg-rest` (iceberg-rest) | `s3` | Catalog storage | default → default | yes |
| 3 | `iceberg-rest` (iceberg-rest) → `trino` (trino) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 4 | `trino` (trino) → `metabase` (metabase) | `sql-query` | SQL | default → default | yes |

### NVIDIA STX: The G3.5 Tier

**File:** `experience-stx-inference.yaml` | **Nodes:** 5 | **Edges:** 6

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `inference-client` (inference-client) → `sim-1` (inference-sim) | `inference-api` | Inference requests | default → default | yes |
| 2 | `sim-1` (inference-sim) → `minio-g35` (minio) | `s3` | G3.5 context memory | `bottom-out` → `data-in-top` | yes |
| 3 | `sim-1` (inference-sim) → `minio-g4` (minio) | `s3` | G4 enterprise storage | `default` → `data-in` | yes |
| 4 | `sim-1` (inference-sim) → `prometheus-1` (prometheus) | `metrics` | Sim metrics | `bottom-out` → `default` | yes |
| 5 | `minio-g35` (minio) → `prometheus-1` (prometheus) | `metrics` | G3.5 metrics | `cluster-out-bottom` → `default` | yes |
| 6 | `minio-g4` (minio) → `prometheus-1` (prometheus) | `metrics` | G4 metrics | `cluster-out-bottom` → `default` | yes |

### Automated ML Pipeline

**File:** `automated-ml-pipeline.yaml` | **Nodes:** 5 | **Edges:** 6

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Raw data | default → default | yes |
| 2 | `airflow-1` (airflow) → `minio-1` (minio) | `s3` | DAGs + logs | default → default | yes |
| 3 | `airflow-1` (airflow) → `trainer-1` (ml-trainer) | `workflow-api` | Trigger training | default → default | yes |
| 4 | `trainer-1` (ml-trainer) → `minio-1` (minio) | `s3` | Training data | default → default | yes |
| 5 | `trainer-1` (ml-trainer) → `mlflow-1` (mlflow) | `mlflow-tracking` | Log experiments | default → default | yes |
| 6 | `mlflow-1` (mlflow) → `minio-1` (minio) | `s3` | Model artifacts | default → default | yes |

### BI Dashboard — AIStor Tables

**File:** `bi-dashboard-aistor-tables.yaml` | **Nodes:** 4 | **Edges:** 3

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `aistor-1` (minio-aistore) | `s3` | Parquet data | default → default | yes |
| 2 | `aistor-1` (minio-aistore) → `trino` (trino) | `s3` | AIStor Tables | default → default | yes |
| 3 | `trino` (trino) → `metabase` (metabase) | `sql-query` | SQL | default → default | yes |

### BI Dashboard — Lakehouse

**File:** `bi-dashboard-lakehouse.yaml` | **Nodes:** 7 | **Edges:** 7

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Parquet data | default → default | yes |
| 2 | `minio-1` (minio) → `iceberg-rest` (iceberg-rest) | `s3` | S3 warehouse | default → default | yes |
| 3 | `iceberg-rest` (iceberg-rest) → `trino` (trino) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 4 | `minio-1` (minio) → `trino` (trino) | `s3` | S3 | default → default | yes |
| 5 | `trino` (trino) → `metabase` (metabase) | `sql-query` | SQL | default → default | yes |
| 6 | `minio-1` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | default → default | yes |
| 7 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### Complete Analytics Platform

**File:** `complete-analytics.yaml` | **Nodes:** 11 | **Edges:** 12

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen-batch` (data-generator) → `minio-1` (minio) | `structured-data` | Parquet batch | default → default | yes |
| 2 | `data-gen-stream` (data-generator) → `redpanda-1` (redpanda) | `kafka` | Produce events | default → default | yes |
| 3 | `rp-console` (redpanda-console) → `redpanda-1` (redpanda) | `kafka` | Manage | default → default | yes |
| 4 | `rp-console` (redpanda-console) → `redpanda-1` (redpanda) | `schema-registry` | — | default → default | yes |
| 5 | `kafka-connect-1` (kafka-connect-s3) → `redpanda-1` (redpanda) | `kafka` | Consume | default → default | yes |
| 6 | `kafka-connect-1` (kafka-connect-s3) → `minio-1` (minio) | `s3` | S3 Sink | default → default | yes |
| 7 | `dremio-1` (dremio) → `minio-1` (minio) | `s3` | S3 | default → default | yes |
| 8 | `dremio-1` (dremio) → `nessie-1` (nessie) | `iceberg-catalog` | Nessie catalog | default → default | yes |
| 9 | `trino-1` (trino) → `minio-1` (minio) | `s3` | S3 query | default → default | yes |
| 10 | `metabase-1` (metabase) → `dremio-1` (dremio) | `dremio-sql` | Dremio SQL | default → default | yes |
| 11 | `metabase-1` (metabase) → `trino-1` (trino) | `sql-query` | SQL | default → default | yes |
| 12 | `minio-1` (minio) → `prometheus-1` (prometheus) | `metrics` | Metrics | `bottom-out` → `default` | yes |

### Customer 360 analytics

**File:** `template-customer-360.yaml` | **Nodes:** 7 | **Edges:** 7

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Parquet data | default → default | yes |
| 2 | `minio-1` (minio) → `iceberg-rest` (iceberg-rest) | `s3` | S3 warehouse | default → default | yes |
| 3 | `iceberg-rest` (iceberg-rest) → `trino` (trino) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 4 | `minio-1` (minio) → `trino` (trino) | `s3` | S3 | default → default | yes |
| 5 | `trino` (trino) → `metabase` (metabase) | `sql-query` | SQL | default → default | yes |
| 6 | `minio-1` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | default → default | yes |
| 7 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### AI Data Labeling Pipeline

**File:** `data-labeling-pipeline.yaml` | **Nodes:** 4 | **Edges:** 3

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Support tickets | default → default | yes |
| 2 | `label-studio-1` (label-studio) → `minio-1` (minio) | `s3` | Read data + write labels | default → default | yes |
| 3 | `jupyter-1` (jupyterlab) → `minio-1` (minio) | `s3` | Train on labeled data | default → default | yes |

### Dremio Lakehouse

**File:** `dremio-lakehouse.yaml` | **Nodes:** 6 | **Edges:** 8

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `structured-data` | Parquet | default → default | yes |
| 2 | `minio-1` (minio) → `iceberg-rest` (iceberg-rest) | `s3` | S3 warehouse | default → default | yes |
| 3 | `dremio-1` (dremio) → `minio-1` (minio) | `s3` | S3 | default → default | yes |
| 4 | `dremio-1` (dremio) → `iceberg-rest` (iceberg-rest) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 5 | `trino-1` (trino) → `minio-1` (minio) | `s3` | S3 | default → default | yes |
| 6 | `trino-1` (trino) → `iceberg-rest` (iceberg-rest) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 7 | `metabase-1` (metabase) → `dremio-1` (dremio) | `dremio-sql` | Dremio SQL | default → default | yes |
| 8 | `metabase-1` (metabase) → `trino-1` (trino) | `sql-query` | SQL | default → default | yes |

### Enterprise Vector Search (Milvus)

**File:** `enterprise-vector-search.yaml` | **Nodes:** 5 | **Edges:** 5

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `milvus-1` (milvus) → `minio-1` (minio) | `s3` | Primary storage | default → default | yes |
| 2 | `milvus-1` (milvus) → `etcd-1` (etcd) | `etcd` | Metadata | `bottom-out` → `default` | yes |
| 3 | `rag-1` (rag-app) → `milvus-1` (milvus) | `vector-db-milvus` | Vector search | default → default | yes |
| 4 | `rag-1` (rag-app) → `ollama-1` (ollama) | `llm-api` | Embed + generate | default → default | yes |
| 5 | `rag-1` (rag-app) → `minio-1` (minio) | `s3` | Docs + audit | default → default | yes |

### Full Analytics Pipeline

**File:** `full-analytics-pipeline.yaml` | **Nodes:** 9 | **Edges:** 9

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `file-gen` (file-generator) → `minio-1` (minio) | `file-push` | — | default → default | yes |
| 2 | `hdfs` (hdfs) → `spark` (spark) | `hdfs` | HDFS read | default → default | yes |
| 3 | `minio-1` (minio) → `spark` (spark) | `s3` | S3A read/write | default → default | yes |
| 4 | `minio-1` (minio) → `iceberg-rest` (iceberg-rest) | `s3` | S3 warehouse | default → default | yes |
| 5 | `iceberg-rest` (iceberg-rest) → `trino` (trino) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 6 | `minio-1` (minio) → `trino` (trino) | `s3` | S3 direct | default → default | yes |
| 7 | `minio-1` (minio) → `clickhouse` (clickhouse) | `s3` | S3 query | default → default | yes |
| 8 | `minio-1` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `bottom-out` → `default` | yes |
| 9 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### Hadoop to MinIO Migration

**File:** `hadoop-migration.yaml` | **Nodes:** 5 | **Edges:** 4

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `hdfs` (hdfs) → `spark` (spark) | `hdfs` | HDFS read | default → default | yes |
| 2 | `minio-1` (minio) → `spark` (spark) | `s3` | S3A | default → default | yes |
| 3 | `minio-1` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | default → default | yes |
| 4 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### MinIO AI Platform

**File:** `minio-ai-platform.yaml` | **Nodes:** 10 | **Edges:** 12

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Raw data | default → default | yes |
| 2 | `label-studio-1` (label-studio) → `minio-1` (minio) | `s3` | Label data | default → default | yes |
| 3 | `jupyter-1` (jupyterlab) → `minio-1` (minio) | `s3` | Explore data | default → default | yes |
| 4 | `jupyter-1` (jupyterlab) → `mlflow-1` (mlflow) | `mlflow-tracking` | Log experiments | default → default | yes |
| 5 | `mlflow-1` (mlflow) → `minio-1` (minio) | `s3` | Artifacts | `bottom-out` → `default` | yes |
| 6 | `trainer-1` (ml-trainer) → `minio-1` (minio) | `s3` | Training data | default → default | yes |
| 7 | `trainer-1` (ml-trainer) → `mlflow-1` (mlflow) | `mlflow-tracking` | Track runs | default → default | yes |
| 8 | `milvus-1` (milvus) → `minio-1` (minio) | `s3` | Vector storage | default → default | yes |
| 9 | `milvus-1` (milvus) → `etcd-1` (etcd) | `etcd` | Metadata | `bottom-out` → `default` | yes |
| 10 | `rag-1` (rag-app) → `milvus-1` (milvus) | `vector-db-milvus` | Vector search | default → default | yes |
| 11 | `rag-1` (rag-app) → `ollama-1` (ollama) | `llm-api` | Embed + generate | default → default | yes |
| 12 | `rag-1` (rag-app) → `minio-1` (minio) | `s3` | Docs + audit | default → default | yes |

### ML Experiment Lab

**File:** `ml-experiment-lab.yaml` | **Nodes:** 5 | **Edges:** 6

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Raw data | default → default | yes |
| 2 | `mlflow-1` (mlflow) → `minio-1` (minio) | `s3` | Model artifacts | default → default | yes |
| 3 | `jupyter-1` (jupyterlab) → `minio-1` (minio) | `s3` | Read/write data | default → default | yes |
| 4 | `jupyter-1` (jupyterlab) → `mlflow-1` (mlflow) | `mlflow-tracking` | Log experiments | default → default | yes |
| 5 | `trainer-1` (ml-trainer) → `minio-1` (minio) | `s3` | Training data | default → default | yes |
| 6 | `trainer-1` (ml-trainer) → `mlflow-1` (mlflow) | `mlflow-tracking` | Track experiments | default → default | yes |

### Multi-cluster replication

**File:** `multi-cluster-replication.yaml` | **Nodes:** 8 | **Edges:** 10

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `nginx-a` (nginx) → `minio-a1` (minio) | `load-balance` | — | default → default | no |
| 2 | `nginx-a` (nginx) → `minio-a2` (minio) | `load-balance` | — | default → default | no |
| 3 | `nginx-b` (nginx) → `minio-b1` (minio) | `load-balance` | — | default → default | no |
| 4 | `nginx-b` (nginx) → `minio-b2` (minio) | `load-balance` | — | default → default | no |
| 5 | `minio-a1` (minio) → `minio-b1` (minio) | `replication` | — | default → default | no |
| 6 | `minio-a1` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 7 | `minio-a2` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 8 | `minio-b1` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 9 | `minio-b2` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 10 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | — | default → default | no |

### Multi-Site Replication

**File:** `multi-site-replication.yaml` | **Nodes:** 5 | **Edges:** 5

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `file-gen` (file-generator) → `minio-site-a` (minio) | `file-push` | — | `default` → `data-in` | no |
| 2 | `minio-site-a` (minio) → `minio-site-b` (minio) | `cluster-replication` | — | `cluster-out-bottom` → `cluster-in-top` | no |
| 3 | `minio-site-a` (minio) → `prometheus` (prometheus) | `metrics` | — | `data-out` → `default` | no |
| 4 | `minio-site-b` (minio) → `prometheus` (prometheus) | `metrics` | — | `data-out` → `default` | no |
| 5 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | — | default → default | no |

### Multi-Site Replication (3-Way)

**File:** `multi-site-replication-3way.yaml` | **Nodes:** 8 | **Edges:** 10

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen-site-a` (file-generator) → `minio-site-a` (minio) | `file-push` | Push to site-a-bucket | `default` → `data-in` | yes |
| 2 | `data-gen-site-b` (file-generator) → `minio-site-b` (minio) | `file-push` | Push to site-b-bucket | `default` → `data-in` | yes |
| 3 | `data-gen-site-c` (file-generator) → `minio-site-c` (minio) | `file-push` | Push to site-c-bucket | `default` → `data-in` | yes |
| 4 | `minio-site-a` (minio) → `minio-site-b` (minio) | `cluster-site-replication` | Site Replication A↔B | default → default | yes |
| 5 | `minio-site-a` (minio) → `minio-site-c` (minio) | `cluster-site-replication` | Site Replication A↔C | default → default | yes |
| 6 | `minio-site-b` (minio) → `minio-site-c` (minio) | `cluster-site-replication` | Site Replication B↔C | default → default | yes |
| 7 | `minio-site-a` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `data-out` → `default` | yes |
| 8 | `minio-site-b` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `data-out` → `default` | yes |
| 9 | `minio-site-c` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `cluster-out-bottom` → `default` | yes |
| 10 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### RAG Pipeline — Enterprise AI on MinIO

**File:** `rag-pipeline.yaml` | **Nodes:** 4 | **Edges:** 4

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `rag-1` (rag-app) → `minio-1` (minio) | `s3` | Docs + audit logs | default → default | yes |
| 2 | `rag-1` (rag-app) → `ollama-1` (ollama) | `llm-api` | Embed + generate | default → default | yes |
| 3 | `rag-1` (rag-app) → `qdrant-1` (qdrant) | `vector-db` | Vector search | default → default | yes |
| 4 | `qdrant-1` (qdrant) → `minio-1` (minio) | `s3` | Snapshot backup | default → default | yes |

### Real-Time Analytics with ClickHouse

**File:** `realtime-analytics.yaml` | **Nodes:** 5 | **Edges:** 4

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `file-gen` (file-generator) → `minio` (minio) | `file-push` | — | default → default | yes |
| 2 | `minio` (minio) → `clickhouse` (clickhouse) | `s3` | S3 query | default → default | yes |
| 3 | `minio` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `bottom-out` → `default` | yes |
| 4 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### Site replication (bidirectional)

**File:** `site-replication.yaml` | **Nodes:** 8 | **Edges:** 10

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `nginx-site1` (nginx) → `minio-site1-a` (minio) | `load-balance` | — | default → default | no |
| 2 | `nginx-site1` (nginx) → `minio-site1-b` (minio) | `load-balance` | — | default → default | no |
| 3 | `nginx-site2` (nginx) → `minio-site2-a` (minio) | `load-balance` | — | default → default | no |
| 4 | `nginx-site2` (nginx) → `minio-site2-b` (minio) | `load-balance` | — | default → default | no |
| 5 | `minio-site1-a` (minio) → `minio-site2-a` (minio) | `site-replication` | — | default → default | no |
| 6 | `minio-site1-a` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 7 | `minio-site1-b` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 8 | `minio-site2-a` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 9 | `minio-site2-b` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 10 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | — | default → default | no |

### Site Replication with Failover

**File:** `site-replication-failover.yaml` | **Nodes:** 7 | **Edges:** 8

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `failover-gw` (nginx) → `minio-site-a` (minio) | `failover` | Primary | `bottom-out` → `data-in-top` | yes |
| 2 | `failover-gw` (nginx) → `minio-site-b` (minio) | `failover` | Backup | `default` → `data-in` | yes |
| 3 | `resilience-tester` (resilience-tester) → `failover-gw` (nginx) | `s3` | Probe | default → default | yes |
| 4 | `file-gen` (file-generator) → `failover-gw` (nginx) | `file-push` | — | default → default | yes |
| 5 | `minio-site-a` (minio) → `minio-site-b` (minio) | `cluster-site-replication` | Site Replication | `cluster-out-bottom` → `cluster-in-top` | yes |
| 6 | `minio-site-a` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `data-out` → `default` | yes |
| 7 | `minio-site-b` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | `cluster-out-bottom` → `default` | yes |
| 8 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### ILM Tiered Storage (Hot → Cold)

**File:** `template-smart-tiering.yaml` | **Nodes:** 8 | **Edges:** 9

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (file-generator) → `nginx-hot` (nginx) | `file-push` | — | `bottom-out` → `default` | no |
| 2 | `nginx-hot` (nginx) → `minio-hot-1` (minio) | `load-balance` | — | default → default | no |
| 3 | `nginx-hot` (nginx) → `minio-hot-2` (minio) | `load-balance` | — | default → default | no |
| 4 | `minio-hot-1` (minio) → `minio-cold-1` (minio) | `tiering` | — | default → default | no |
| 5 | `minio-hot-1` (minio) → `prometheus` (prometheus) | `metrics` | — | `bottom-out` → `default` | no |
| 6 | `minio-hot-2` (minio) → `prometheus` (prometheus) | `metrics` | — | `bottom-out` → `default` | no |
| 7 | `minio-cold-1` (minio) → `prometheus` (prometheus) | `metrics` | — | `bottom-out` → `default` | no |
| 8 | `minio-cold-2` (minio) → `prometheus` (prometheus) | `metrics` | — | default → default | no |
| 9 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | — | default → default | no |

### Real-time Streaming Lakehouse

**File:** `streaming-lakehouse.yaml` | **Nodes:** 7 | **Edges:** 7

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `redpanda-1` (redpanda) | `kafka` | Produce events | default → default | yes |
| 2 | `rp-console` (redpanda-console) → `redpanda-1` (redpanda) | `kafka` | Manage | default → default | yes |
| 3 | `rp-console` (redpanda-console) → `redpanda-1` (redpanda) | `schema-registry` | — | default → default | yes |
| 4 | `kafka-connect-1` (kafka-connect-s3) → `redpanda-1` (redpanda) | `kafka` | Consume | default → default | yes |
| 5 | `kafka-connect-1` (kafka-connect-s3) → `minio-1` (minio) | `s3` | S3 Sink | default → default | yes |
| 6 | `trino-1` (trino) → `minio-1` (minio) | `s3` | S3 query | default → default | yes |
| 7 | `metabase-1` (metabase) → `trino-1` (trino) | `sql-query` | SQL | default → default | yes |

### Time Travel — Iceberg Snapshots

**File:** `template-time-travel.yaml` | **Nodes:** 7 | **Edges:** 7

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `s3` | Parquet data | default → default | yes |
| 2 | `minio-1` (minio) → `iceberg-rest` (iceberg-rest) | `s3` | S3 warehouse | default → default | yes |
| 3 | `iceberg-rest` (iceberg-rest) → `trino` (trino) | `iceberg-catalog` | Iceberg catalog | default → default | yes |
| 4 | `minio-1` (minio) → `trino` (trino) | `s3` | S3 | default → default | yes |
| 5 | `trino` (trino) → `metabase` (metabase) | `sql-query` | SQL | default → default | yes |
| 6 | `minio-1` (minio) → `prometheus` (prometheus) | `metrics` | Metrics | default → default | yes |
| 7 | `prometheus` (prometheus) → `grafana` (grafana) | `metrics-query` | PromQL | default → default | yes |

### Versioned Data Lake

**File:** `versioned-data-lake.yaml` | **Nodes:** 5 | **Edges:** 4

| # | Source → Target | Connection Type | Label | Handles (src → tgt) | Auto |
|---|----------------|-----------------|-------|---------------------|------|
| 1 | `data-gen` (data-generator) → `minio-1` (minio) | `structured-data` | Structured data | default → default | yes |
| 2 | `dremio-1` (dremio) → `minio-1` (minio) | `s3` | S3 | default → default | yes |
| 3 | `dremio-1` (dremio) → `nessie-1` (nessie) | `iceberg-catalog` | Nessie catalog | default → default | yes |
| 4 | `metabase-1` (metabase) → `dremio-1` (dremio) | `dremio-sql` | Dremio SQL | default → default | yes |

---

## Handle Usage Summary

Available handles on **ComponentNode** (regular nodes):
| Position | Type | Handle ID | Visible |
|----------|------|-----------|---------|
| Left | target | `left` | yes (black dot) |
| Left | source | `left-out` | hidden (overlaid) |
| Top | target | `top` | yes (black dot) |
| Top | source | `top-out` | hidden (overlaid) |
| Right | source | `right` | yes (black dot) |
| Right | target | `right-in` | hidden (overlaid) |
| Bottom | source | `bottom-out` | yes (black dot) |
| Bottom | target | `bottom` | hidden (overlaid) |
| Left | target | *(default, no id)* | hidden (backward compat) |
| Right | source | *(default, no id)* | hidden (backward compat) |

Available handles on **ClusterNode**:
| Position | Type | Handle ID | Visible |
|----------|------|-----------|---------|
| Left | target | `data-in` | yes |
| Top | target | `data-in-top` | yes |
| Top | source | `cluster-out` | yes (blue, cluster-to-cluster) |
| Top | target | `cluster-in-top` | hidden (blue) |
| Bottom | target | `cluster-in` | yes (blue, cluster-to-cluster) |
| Bottom | source | `cluster-out-bottom` | hidden (blue) |
| Right | source | `data-out` | yes |

---

## Designer Coverage

All 25 template connection types are registered in `frontend/src/lib/connectionMeta.ts` with colors and labels — **all drawable from the designer**.

10 additional types are defined in the frontend but not yet used in any template:

| Type | Label | Color | Status |
|------|-------|-------|--------|
| `aistor-tables` | AIStor Tables (SigV4 Iceberg) | #1565c0 | Available for manual use |
| `cluster-tiering` | ILM Tiering | #eab308 | Available for manual use |
| `data` | Data | #6b7280 | Available for manual use |
| `dremio-flight` | Arrow Flight | #6d28d9 | Available for manual use |
| `http` | HTTP | #6b7280 | Available for manual use |
| `kafka-connect` | Kafka Connect | #be123c | Available for manual use |
| `labeling-api` | Labeling API | #f472b6 | Available for manual use |
| `llm-gateway` | LLM Gateway | #8b5cf6 | Available for manual use |
| `s3-queue` | S3 Queue | #00897b | Available for manual use |
| `spark-submit` | Spark Submit | #e65100 | Available for manual use |

---

## Notes

- Edges with `default → default` handles use React Flow's implicit handle matching (left target, right source)
- Users can delete any edge and redraw from any handle to any handle — the chosen handles are persisted on save
- `auto_configure: true` means the backend runs init scripts to set up the connection (replication, metrics scraping, etc.)
- Cluster-to-cluster edges (`cluster-replication`, `cluster-site-replication`, `tiering`) use the blue cluster handles
- The `connection_type` determines the edge color, label, and what automation runs on deploy
- To regenerate this inventory: `python3 scripts/fix_template_connections.py --dry-run` + scan script
