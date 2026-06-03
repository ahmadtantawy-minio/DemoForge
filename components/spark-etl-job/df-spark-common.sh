# Shared spark-submit helpers for entrypoint.sh and df-run-spark-submit.sh (sourced, not executed).

_DF_SPARK_EXTRA_JARS="/opt/spark/jars/hadoop-aws-3.3.4.jar,/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar,/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar,/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar"
_DF_DRIVER_CP="/opt/spark/jars/hadoop-aws-3.3.4.jar:/opt/spark/jars/aws-java-sdk-bundle-1.12.262.jar:/opt/spark/jars/iceberg-spark-runtime-3.5_2.12-1.5.0.jar:/opt/spark/jars/iceberg-aws-bundle-1.5.0.jar"

SPARK_RUN_LOG="${SPARK_RUN_LOG:-/tmp/demoforge-spark-runs.ndjson}"
SPARK_SUBMIT_LOG="${SPARK_SUBMIT_LOG:-/tmp/demoforge-spark-submit-last.log}"
DF_SPARK_SUBMIT_LOCK="${DF_SPARK_SUBMIT_LOCK:-/tmp/demoforge-spark-submit.lock}"

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

df_exec_iceberg_compaction_submit() {
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
    /opt/demoforge/jobs/iceberg_catalog_compaction.py
}

df_exec_submit() {
  local mode="${JOB_MODE:-raw_to_iceberg}"
  if [[ "$mode" == "raw_to_parquet" ]]; then
    df_exec_raw_to_parquet_submit
  elif [[ "$mode" == "iceberg_compaction" ]]; then
    df_exec_iceberg_compaction_submit
  else
    df_exec_raw_to_iceberg_submit
  fi
}

df_exec_submit_logged() {
  : >"$SPARK_SUBMIT_LOG" 2>/dev/null || true
  set +e
  df_exec_submit 2>&1 | tee -a "$SPARK_SUBMIT_LOG"
  local rc=${PIPESTATUS[0]}
  set -e
  return "$rc"
}

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

df_normalize_job_mode() {
  local mode="${JOB_MODE:-raw_to_iceberg}"
  local tpl="${JOB_TEMPLATE:-}"
  if [[ -n "$tpl" && "$mode" == "raw_to_iceberg" ]]; then
    if [[ "$tpl" == "csv_glob_to_iceberg" || "$tpl" == "raw_to_iceberg" ]]; then
      mode="raw_to_iceberg"
    fi
  fi
  if [[ "$mode" != "raw_to_iceberg" && "$mode" != "raw_to_parquet" && "$mode" != "iceberg_compaction" ]]; then
    echo "[spark-etl-job] Unknown JOB_MODE=$mode" >&2
    return 1
  fi
  echo "$mode"
}

# Run one spark-submit with NDJSON logging. Returns spark-submit exit code.
df_run_spark_submit_once() {
  local job_mode
  job_mode="$(df_normalize_job_mode)" || return 1
  : "${SPARK_MASTER_URL:?SPARK_MASTER_URL required}"

  if [[ "$job_mode" == "iceberg_compaction" ]]; then
    echo "[spark-etl-job] Submitting iceberg_compaction to $SPARK_MASTER_URL (REST catalog maintenance)"
  else
    echo "[spark-etl-job] Submitting ${job_mode} to $SPARK_MASTER_URL (RAW_INPUT_FORMAT=${RAW_INPUT_FORMAT:-csv})"
  fi

  spark_run_log spark_submit_start ""
  df_spark_submit_preflight
  df_log_spark_submit_invocation
  set +e
  df_exec_submit_logged
  local rc=$?
  set -e
  spark_run_log spark_submit_finished "$rc"
  if [[ "$rc" -ne 0 ]]; then
    echo "[spark-etl-job] ERROR spark-submit failed with exit code $rc"
  else
    echo "[spark-etl-job] spark-submit succeeded (exit $rc)"
  fi
  return "$rc"
}
