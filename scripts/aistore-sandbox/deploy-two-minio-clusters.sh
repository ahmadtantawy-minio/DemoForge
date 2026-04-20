#!/usr/bin/env bash
# Convenience entrypoint — all logic lives in deploy-two-cluster.sh (Mode 1).
set -euo pipefail
export AISTOR_TWO_MINIO_NAMESPACES=1
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy-two-cluster.sh"
