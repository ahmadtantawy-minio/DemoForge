#!/bin/bash
set -euo pipefail

# --jars: ship deps to the standalone cluster. --driver-class-path: PySpark driver JVM loads SparkSession + Hadoop FS
# classes from the *bootstrap* classloader before --jars are visible — without this, S3A + Iceberg extensions CNFE.
_DF_SPARK_EXTRA_JARS="/opt/spark/jars/hadoop-aws-3.3.4.jar,/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar,/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar,/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar"
_DF_DRIVER_CP="/opt/spark/jars/hadoop-aws-3.3.4.jar:/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar:/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar:/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar"

SPARK_RUN_LOG="${SPARK_RUN_LOG:-/tmp/demoforge-spark-runs.ndjson}"

# Logs jar presence, paths, and spark-submit identity — copy into support tickets when S3A/Iceberg CNFE persists.
df_spark_submit_preflight() {
  echo "[spark-etl-job] DIAG-PREFLIGHT hostname=$(hostname) uid=$(id -u 2>/dev/null || echo '?')"
  echo "[spark-etl-job] DIAG-PREFLIGHT SPARK_HOME=${SPARK_HOME:-unset} JAVA_HOME=${JAVA_HOME:-unset}"
  if [[ -x /opt/spark/bin/spark-submit ]]; then
    echo "[spark-etl-job] DIAG-PREFLIGHT spark-submit=/opt/spark/bin/spark-submit (PATH may omit it: $(command -v spark-submit 2>/dev/null || echo 'not-on-PATH'))"
  else
    echo "[spark-etl-job] DIAG-PREFLIGHT spark-submit=MISSING_OR_NOT_EXECUTABLE (/opt/spark/bin/spark-submit)"
  fi
  echo "[spark-etl-job] DIAG-PREFLIGHT driver-class-path=${_DF_DRIVER_CP}"
  echo "[spark-etl-job] DIAG-PREFLIGHT --jars list:"
  local j
  IFS=',' read -ra _df_jars <<< "${_DF_SPARK_EXTRA_JARS}"
  for j in "${_df_jars[@]}"; do
    j="${j//$'\r'/}"
    j="${j#"${j%%[![:space:]]*}"}"
    j="${j%"${j##*[![:space:]]}"}"
    [[ -z "$j" ]] && continue
    if [[ ! -e "$j" ]]; then
      echo "[spark-etl-job] DIAG-PREFLIGHT   MISSING path=$j"
    elif [[ ! -r "$j" ]]; then
      echo "[spark-etl-job] DIAG-PREFLIGHT   EXISTS_NOT_READABLE path=$j"
    else
      sz=$(wc -c <"$j" 2>/dev/null || echo "?")
      echo "[spark-etl-job] DIAG-PREFLIGHT   OK size=${sz} path=$j"
    fi
  done
  echo "[spark-etl-job] DIAG-PREFLIGHT spark-submit --version (first lines):"
  /opt/spark/bin/spark-submit --version 2>&1 | head -5 | while IFS= read -r line || [[ -n "$line" ]]; do
    echo "[spark-etl-job] DIAG-PREFLIGHT   $line"
  done
}

df_log_spark_submit_invocation() {
  echo "[spark-etl-job] DIAG spark-submit effective master=${SPARK_MASTER_URL:-unset}"
  echo "[spark-etl-job] DIAG env hooks PYSPARK_SUBMIT_ARGS=${PYSPARK_SUBMIT_ARGS:-<empty>} SPARK_SUBMIT_OPTS=${SPARK_SUBMIT_OPTS:-<empty>}"
  echo "[spark-etl-job] DIAG --jars (comma): ${_DF_SPARK_EXTRA_JARS}"
  echo "[spark-etl-job] DIAG --driver-class-path (colon): ${_DF_DRIVER_CP}"
  echo "[spark-etl-job] TIP Spark Master UI must show ≥1 alive worker and URL must NOT be spark://0.0.0.0:7077 (that breaks worker registration). Redeploy/regenerate compose after Spark manifest updates."
}

# Expand --master at call time (not at script parse) so SPARK_MASTER_URL is always current.
df_exec_raw_to_iceberg_submit() {
  /opt/spark/bin/spark-submit \
    --master "${SPARK_MASTER_URL}" \
    --deploy-mode client \
    --conf "spark.driver.memory=512m" \
    --conf "spark.executor.memory=512m" \
    --conf "spark.executor.cores=1" \
    --conf "spark.cores.max=1" \
    --jars "${_DF_SPARK_EXTRA_JARS}" \
    --driver-class-path "${_DF_DRIVER_CP}" \
    --conf "spark.executor.extraClassPath=${_DF_DRIVER_CP}" \
    /opt/demoforge/jobs/csv_glob_to_iceberg.py
}

df_exec_raw_to_parquet_submit() {
  /opt/spark/bin/spark-submit \
    --master "${SPARK_MASTER_URL}" \
    --deploy-mode client \
    --conf "spark.driver.memory=512m" \
    --conf "spark.executor.memory=512m" \
    --conf "spark.executor.cores=1" \
    --conf "spark.cores.max=1" \
    --jars "${_DF_SPARK_EXTRA_JARS}" \
    --driver-class-path "${_DF_DRIVER_CP}" \
    --conf "spark.executor.extraClassPath=${_DF_DRIVER_CP}" \
    /opt/demoforge/jobs/raw_to_parquet.py
}

# Dispatch to the right submit function based on JOB_MODE
df_exec_submit() {
  local mode="${JOB_MODE:-raw_to_iceberg}"
  if [[ "$mode" == "raw_to_parquet" ]]; then
    df_exec_raw_to_parquet_submit
  else
    df_exec_raw_to_iceberg_submit
  fi
}

# Append one NDJSON record (phase, optional exit_code, status/success for UI).
spark_run_log() {
  local phase="$1"
  local ec="${2:-}"
  _SPARK_LOG_PHASE="$phase" _SPARK_LOG_EC="$ec" python3 -c 'import json, os, time
phase = os.environ.get("_SPARK_LOG_PHASE", "")
ec_raw = os.environ.get("_SPARK_LOG_EC", "").strip()
try:
    ec = int(ec_raw) if ec_raw != "" else None
except ValueError:
    ec = None
row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "phase": phase,
    "schedule": os.environ.get("JOB_SCHEDULE", ""),
    "exit_code": ec,
}
if phase == "spark_submit_start":
    # Point-in-time log line (append-only): job is not "still running" when you read history later.
    row["status"] = "submitted"
elif phase == "spark_submit_finished":
    ok = ec == 0 if ec is not None else False
    row["success"] = ok
    row["status"] = "ok" if ok else "error"
elif phase == "manual_idle":
    row["status"] = "idle"
else:
    row["status"] = "unknown"
print(json.dumps(row))' >>"$SPARK_RUN_LOG" 2>/dev/null || true
}

sched="${JOB_SCHEDULE:-on_deploy_once}"

job_mode="${JOB_MODE:-raw_to_iceberg}"

if [[ "$sched" == "manual" ]]; then
  echo "[spark-etl-job] JOB_SCHEDULE=manual, JOB_MODE=${job_mode} — container idle. Example:"
  echo "  spark-submit --master \"\$SPARK_MASTER_URL\" --deploy-mode client --jars \"${_DF_SPARK_EXTRA_JARS}\" \\"
  echo "    --driver-class-path \"${_DF_DRIVER_CP}\" --conf spark.executor.extraClassPath=${_DF_DRIVER_CP} \\"
  if [[ "$job_mode" == "raw_to_parquet" ]]; then
    echo "    /opt/demoforge/jobs/raw_to_parquet.py"
  else
    echo "    /opt/demoforge/jobs/csv_glob_to_iceberg.py"
  fi
  spark_run_log manual_idle ""
  exec tail -f /dev/null
fi

if [[ "$sched" == "interval" ]]; then
  interval="${JOB_INTERVAL_SEC:-300}"
  echo "[spark-etl-job] JOB_SCHEDULE=interval, JOB_MODE=${job_mode} — submitting every ${interval}s (Ctrl+C stops loop in dev)"
  echo "[spark-etl-job] Scheduling note: each iteration waits for spark-submit to exit before sleeping — no overlap within this container."
  while true; do
    spark_run_log spark_submit_start ""
    df_spark_submit_preflight
    df_log_spark_submit_invocation
    set +e
    df_exec_submit
    rc=$?
    set -e
    spark_run_log spark_submit_finished "$rc"
    if [[ "$rc" -ne 0 ]]; then
      echo "[spark-etl-job] ERROR spark-submit failed (exit $rc) — sleeping ${interval}s"
    else
      echo "[spark-etl-job] spark-submit succeeded (exit $rc) — sleeping ${interval}s"
    fi
    sleep "$interval"
  done
fi

if [[ "$sched" != "on_deploy_once" ]]; then
  echo "[spark-etl-job] Unsupported JOB_SCHEDULE=$sched — idling."
  exec tail -f /dev/null
fi

# Legacy JOB_TEMPLATE compat: normalize to JOB_MODE
tpl="${JOB_TEMPLATE:-}"
if [[ -n "$tpl" && "$job_mode" == "raw_to_iceberg" ]]; then
  if [[ "$tpl" == "csv_glob_to_iceberg" || "$tpl" == "raw_to_iceberg" ]]; then
    job_mode="raw_to_iceberg"
  fi
fi
if [[ "$job_mode" != "raw_to_iceberg" && "$job_mode" != "raw_to_parquet" ]]; then
  echo "[spark-etl-job] Unknown JOB_MODE=$job_mode — idling."
  exec tail -f /dev/null
fi

: "${SPARK_MASTER_URL:?SPARK_MASTER_URL required}"

echo "[spark-etl-job] Submitting ${job_mode} to $SPARK_MASTER_URL (RAW_INPUT_FORMAT=${RAW_INPUT_FORMAT:-csv})"

spark_run_log spark_submit_start ""
df_spark_submit_preflight
df_log_spark_submit_invocation
set +e
df_exec_submit
rc=$?
set -e
spark_run_log spark_submit_finished "$rc"
if [[ "$rc" -ne 0 ]]; then
  echo "[spark-etl-job] ERROR spark-submit failed with exit code $rc — container staying up for logs."
else
  echo "[spark-etl-job] spark-submit succeeded (exit $rc) — container staying up for logs."
fi
exec tail -f /dev/null
