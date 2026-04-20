# Remote MinIO Console (cluster B → API on cluster A)

## Topology (default in-repo)

- **Cluster A (DATA):** AIStor operator + ObjectStore only. S3 API Service stays **ClusterIP** (in-cluster). Operator-managed Console Service in `values.yaml` is **ClusterIP** as well (not exposed outside the cluster; optional port-forward for debugging).
- **Cluster B (UI):** **No** `aistor-objectstore` Helm release and **no** MinIO pools, PVCs, or S3 StatefulSets. Only the manifests in this folder: a single Console `Deployment`, JWT `Secret`, and **ClusterIP** `Service` (`df-cursor-console-remote`). Nothing on B advertises an S3 endpoint.
- **Where the API URL is set:** `deploy-remote-console.sh` writes `REMOTE_MINIO_URL` (or `CONSOLE_MINIO_SERVER_URL`) into ConfigMap `df-cursor-console-remote-endpoint` as key `CONSOLE_MINIO_SERVER`, which the Console pod consumes as env `CONSOLE_MINIO_SERVER`. That is the “override MinIO URL on the second cluster” hook.

For automated wiring (cleanup, DATA deploy, URL resolution, `CONSOLE_IMAGE` detection), use `scripts/aistore-sandbox/deploy-two-cluster.sh`. Override the API URL with **`AISTOR_REMOTE_S3_URL_OVERRIDE`** when auto-detection is wrong. For a manual B-only deploy, export **`REMOTE_MINIO_URL`** or **`CONSOLE_MINIO_SERVER_URL`**.

## Prerequisites

1. **Cluster A** runs the AIStor ObjectStore; pods on **cluster B** can open a TCP connection to the MinIO API URL you configure (port often `9000` for plain HTTP, or TLS as you terminate it).
2. **TLS:** If cluster A’s API presents a cert B cannot trust, fix trust or terminate TLS in front with a cert B trusts. This Console chart does not replace MinIO TLS on A.

## Deploy (kubectl context = cluster B)

From repo root:

```bash
# Defaults: KUBECTL_CONTEXT=demoforge-aistore-console, REMOTE_CONSOLE_DATA_KUBE_CONTEXT=demoforge-aistore-data (for labels)
export KUBECTL_CONTEXT='your-ui-cluster-context'   # override if your kube context name differs
export REMOTE_MINIO_URL='https://minio-api.cluster-a.example:9000'   # reachable from cluster B
# Optional alias: export CONSOLE_MINIO_SERVER_URL='…'   # used if REMOTE_MINIO_URL is unset
# Required: same image as the operator Console workload on cluster A.
export CONSOLE_IMAGE='…copy from kubectl get deploy,sts -n df-cursor-aistor -o wide …'

./scripts/aistore-sandbox/deploy-remote-console.sh
```

### Full two-cluster automation

`scripts/aistore-sandbox/deploy-two-cluster.sh` (default `AISTOR_DEPLOY_REMOTE_CONSOLE=1`: DATA ObjectStore on A + remote Console on B; set `AISTOR_DEPLOY_REMOTE_CONSOLE=0` for operator-only Console on A).

Right after startup it prints **Kubernetes targets — CLUSTER A vs CLUSTER B** with each context’s **API server URL** from your kubeconfig and a one-line **Evidence** line (same context, same URL / two aliases, or two different URLs). That is how you confirm one versus two control planes from script output alone.

Then port-forward the Console Service on cluster B and open the UI. Log in with the **root credentials from cluster A**.

## Remove

```bash
kubectl delete namespace "${CONSOLE_REMOTE_NS:-df-cursor-console-remote}"
```

(Adjust `CONSOLE_REMOTE_NS` if you overrode it.)
