#!/bin/bash
# On-demand spark-submit (UI / API). Logs to demoforge-spark-runs.ndjson like entrypoint.sh.
set -euo pipefail

. /opt/demoforge/df-spark-common.sh

usage() {
  echo "Usage: $0 [--background]" >&2
  echo "  Runs one spark-submit for JOB_MODE with a non-blocking lock." >&2
  exit 1
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage

if [[ "${1:-}" == "--background" ]]; then
  nohup "$0" </dev/null >>/tmp/demoforge-spark-trigger.log 2>&1 &
  echo "started pid=$!"
  exit 0
fi

exec 9>"$DF_SPARK_SUBMIT_LOCK"
if ! flock -n 9; then
  echo "[df-run-spark-submit] another spark-submit is already running (lock: $DF_SPARK_SUBMIT_LOCK)" >&2
  exit 2
fi

df_run_spark_submit_once
exit $?
