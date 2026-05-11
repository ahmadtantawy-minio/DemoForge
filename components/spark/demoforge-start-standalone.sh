#!/usr/bin/env bash
# DemoForge: Spark standalone master + one or more workers in one container.
# Master RPC must advertise a non-loopback IPv4 so other containers can spark-submit to this service.
# Web UI binds 0.0.0.0 via spark.ui.host in mounted spark-defaults.conf (localhost healthchecks).
set -euo pipefail

SPARK_MASTER_PORT="${SPARK_MASTER_PORT:-7077}"
SPARK_MASTER_WEBUI_PORT="${SPARK_MASTER_WEBUI_PORT:-8080}"

demoforge_pick_primary_ipv4() {
  # hostname -I (capital I): all addresses — prefer first non-loopback (Docker bridge / eth0).
  local ip
  if ip="$(hostname -I 2>/dev/null)"; then
    ip="$(echo "$ip" | awk '{for(i=1;i<=NF;i++) if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $i !~ /^127\./) {print $i; exit}}')"
    if [[ -n "${ip}" ]]; then
      echo "${ip}"
      return 0
    fi
  fi
  # Fallback: hostname -i (order varies by image)
  ip="$(hostname -i 2>/dev/null | tr ' ' '\n' | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $0 !~ /^127\./ {print; exit}')"
  if [[ -n "${ip}" ]]; then
    echo "${ip}"
    return 0
  fi
  return 1
}

demoforge_log_tail_worker_logs() {
  echo "[demoforge-spark] --- grep Worker/Master (last 50 matching lines in /opt/spark/logs) ---"
  shopt -s nullglob
  local f
  for f in /opt/spark/logs/*.out; do
    if grep -q -E 'Worker|worker|Master:|Registration|RegisterWorker|ERROR|FATAL|WARN.*[Ww]orker' "$f" 2>/dev/null; then
      echo "[demoforge-spark] file $(basename "$f"):"
      grep -E 'Worker|worker|Master:|Registration|RegisterWorker|ERROR|FATAL|WARN.*[Ww]orker' "$f" 2>/dev/null | tail -n 25 || true
    fi
  done
  shopt -u nullglob
}

demoforge_master_workers_snapshot() {
  local attempt="$1"
  local js
  echo "[demoforge-spark] Master UI worker check (${attempt}) — GET http://127.0.0.1:${SPARK_MASTER_WEBUI_PORT}/json/"
  js="$(curl -sf --max-time 8 "http://127.0.0.1:${SPARK_MASTER_WEBUI_PORT}/json/" || true)"
  if [[ -z "${js}" ]]; then
    echo "[demoforge-spark] WARN empty Master /json response (UI still starting or curl failed)"
    return 0
  fi
  if ! printf '%s' "${js}" | python3 -c "
import json
import sys

try:
    d = json.load(sys.stdin)
except Exception as e:
    print('[demoforge-spark] WARN Master /json parse error:', e)
    sys.exit(1)

alive = d.get('aliveworkers', d.get('aliveWorkers'))
status = d.get('status')
print('[demoforge-spark] Master UI snapshot status=%r aliveworkers=%r' % (status, alive))
ws = d.get('workers') or []
print('[demoforge-spark] worker rows in Master JSON=%d' % len(ws))
for i, w in enumerate(ws[:16]):
    wid = w.get('id', '?')
    st = w.get('state', '?')
    cores = w.get('cores', w.get('coresfree', '?'))
    mem = w.get('memory', w.get('memoryfree', '?'))
    addr = w.get('host', '?')
    print('[demoforge-spark]   [%d] id=%s state=%s host=%s cores=%s memory=%s' % (i, wid, st, addr, cores, mem))
if len(ws) > 16:
    print('[demoforge-spark]   … %d more workers in JSON' % (len(ws) - 16))
"; then
    echo "[demoforge-spark] WARN python snapshot failed"
  fi
}

if ! _ip="$(demoforge_pick_primary_ipv4)"; then
  echo "[demoforge-spark] FATAL: could not determine non-loopback IPv4 (hostname -I '$(hostname -I 2>/dev/null || true)' hostname -i '$(hostname -i 2>/dev/null || true)')"
  exit 1
fi

export SPARK_MASTER_HOST="${_ip}"

worker_count="${DEMOFORGE_SPARK_WORKER_COUNT:-1}"
if ! [[ "${worker_count}" =~ ^[0-9]+$ ]] || [[ "${worker_count}" -lt 1 ]]; then
  echo "[demoforge-spark] WARN invalid DEMOFORGE_SPARK_WORKER_COUNT='${DEMOFORGE_SPARK_WORKER_COUNT:-}' — using 1"
  worker_count=1
fi
if [[ "${worker_count}" -gt 16 ]]; then
  echo "[demoforge-spark] WARN capping DEMOFORGE_SPARK_WORKER_COUNT at 16 (was ${worker_count})"
  worker_count=16
fi

echo "[demoforge-spark] SPARK_MASTER_HOST=${SPARK_MASTER_HOST} SPARK_MASTER_PORT=${SPARK_MASTER_PORT}"
echo "[demoforge-spark] DEMOFORGE_SPARK_WORKER_COUNT=${worker_count} SPARK_DAEMON_MEMORY=${SPARK_DAEMON_MEMORY:-unset} SPARK_WORKER_MEMORY=${SPARK_WORKER_MEMORY:-unset} SPARK_WORKER_CORES=${SPARK_WORKER_CORES:-unset}"

# With SPARK_NO_DAEMONIZE=true, start-master.sh runs the Master JVM in the *foreground* and never returns —
# we must background it or workers never start (Master UI shows 0 workers, apps WAITING).
echo "[demoforge-spark] launching Master in background, then workers"
/opt/spark/sbin/start-master.sh &
_demoforge_master_pid=$!
sleep 8
if ! kill -0 "${_demoforge_master_pid}" 2>/dev/null; then
  echo "[demoforge-spark] WARN starter PID ${_demoforge_master_pid} ended (Spark may have re-parented); continuing"
fi

worker_pids=()
for ((i = 1; i <= worker_count; i++)); do
  # Master uses 8080; workers use distinct web UI ports for multi-worker on one host.
  _wu=$((SPARK_MASTER_WEBUI_PORT + i))
  echo "[demoforge-spark] starting worker ${i}/${worker_count} webui=${_wu} -> spark://${SPARK_MASTER_HOST}:${SPARK_MASTER_PORT}"
  /opt/spark/sbin/start-worker.sh --webui-port "${_wu}" "spark://${SPARK_MASTER_HOST}:${SPARK_MASTER_PORT}" &
  worker_pids+=($!)
  sleep 2
done

if ((${#worker_pids[@]})); then
  echo "[demoforge-spark] worker PIDs: ${worker_pids[*]}"
else
  echo "[demoforge-spark] ERROR no worker processes started"
  exit 1
fi
sleep 4
demoforge_log_tail_worker_logs

for attempt in 1 2 3; do
  demoforge_master_workers_snapshot "${attempt}/3"
  sleep 4
done

_js_last="$(curl -sf --max-time 8 "http://127.0.0.1:${SPARK_MASTER_WEBUI_PORT}/json/" || true)"
alive_last="$(printf '%s' "${_js_last}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    v = d.get('aliveworkers', d.get('aliveWorkers', 0))
    print(int(v))
except Exception:
    print(-1)
" 2>/dev/null || echo -1)"

if [[ "${alive_last}" =~ ^[0-9]+$ ]] && [[ "${alive_last}" -lt "${worker_count}" ]]; then
  echo "[demoforge-spark] ERROR expected at least ${worker_count} alive worker(s) but Master reports aliveworkers=${alive_last}"
  echo "[demoforge-spark] HINT raise DEMOFORGE_SPARK_CONTAINER_MEM / lower SPARK_DAEMON_MEMORY / SPARK_WORKER_MEMORY / worker count; check OOM or port clashes."
  demoforge_log_tail_worker_logs
fi

shopt -s nullglob
_logs=(/opt/spark/logs/*)
shopt -u nullglob
if ((${#_logs[@]})); then
  echo "[demoforge-spark] following log files: ${_logs[*]}"
  exec tail -n 0 -f "${_logs[@]}"
fi
exec tail -f /dev/null
