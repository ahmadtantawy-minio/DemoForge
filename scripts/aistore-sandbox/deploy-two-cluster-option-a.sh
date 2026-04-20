#!/usr/bin/env bash
# Compatibility wrapper — use deploy-two-cluster.sh
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy-two-cluster.sh" "$@"
