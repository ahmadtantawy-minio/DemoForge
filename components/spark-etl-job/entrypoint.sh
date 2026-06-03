#!/bin/bash
set -euo pipefail

. /opt/demoforge/df-spark-common.sh

sched="${JOB_SCHEDULE:-on_deploy_once}"
job_mode="${JOB_MODE:-raw_to_iceberg}"

if [[ "$sched" == "manual" || "$sched" == "on_demand" ]]; then
  echo "[spark-etl-job] JOB_SCHEDULE=${sched}, JOB_MODE=${job_mode} — container idle until triggered."
  echo "[spark-etl-job] Use the canvas context menu “Run Spark job now”, or:"
  echo "  /opt/demoforge/df-run-spark-submit.sh --background"
  spark_run_log manual_idle ""
  exec tail -f /dev/null
fi

if [[ "$sched" == "interval" ]]; then
  interval="${JOB_INTERVAL_SEC:-300}"
  echo "[spark-etl-job] JOB_SCHEDULE=interval, JOB_MODE=${job_mode} — submitting every ${interval}s (Ctrl+C stops loop in dev)"
  echo "[spark-etl-job] Scheduling note: each iteration waits for spark-submit to exit before sleeping — no overlap within this container."
  while true; do
    df_run_spark_submit_once || true
    sleep "$interval"
  done
fi

if [[ "$sched" != "on_deploy_once" ]]; then
  echo "[spark-etl-job] Unsupported JOB_SCHEDULE=$sched — idling."
  exec tail -f /dev/null
fi

df_run_spark_submit_once || true
exec tail -f /dev/null
