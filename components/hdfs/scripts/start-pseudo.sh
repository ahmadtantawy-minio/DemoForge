#!/bin/bash
# Pseudo-distributed HDFS bootstrap for DemoForge.
set -euo pipefail
NN_DIR="${ENSURE_NAMENODE_DIR:-/tmp/hadoop-root/dfs/name}"
mkdir -p "$NN_DIR" "${HDFS_DATANODE_DIR:-/tmp/hadoop-root/dfs/data}"
if [ ! -f "$NN_DIR/current/VERSION" ]; then
  echo "Formatting NameNode at $NN_DIR"
  hdfs namenode -format -force -nonInteractive
fi
echo "Starting NameNode..."
hdfs namenode &
for i in $(seq 1 90); do
  if (echo > /dev/tcp/127.0.0.1/8020) >/dev/null 2>&1; then
    echo "NameNode RPC ready on :8020"
    break
  fi
  sleep 2
done
echo "Starting DataNode..."
hdfs datanode &
wait
