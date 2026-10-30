#!/usr/bin/env bash
# Tapis ZIP entry point for the NodeSplat app. ClusterODX injects the per-job
# NODESPLAT_* values; everything here is derived from the Tapis job or from
# operator-set variables, never from user input.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")" && pwd)
: "${_tapisJobUUID:?_tapisJobUUID is required}"
: "${_tapisJobWorkingDir:?_tapisJobWorkingDir is required}"
: "${NODESPLAT_PORT:?NODESPLAT_PORT is required}"

export NODESPLAT_TAPIS_JOB_ID="$_tapisJobUUID"
export NODESPLAT_WORK_ROOT="${NODESPLAT_WORK_ROOT:-$_tapisJobWorkingDir/nodesplat-work}"
mkdir -p "$NODESPLAT_WORK_ROOT"
# The address ClusterODX can reach; override when the compute node name is not routable.
export NODESPLAT_PUBLIC_URL="${NODESPLAT_PUBLIC_URL:-http://$(hostname -f):$NODESPLAT_PORT}"

NODE_BIN=${NODESPLAT_NODE_BIN:-node}
command -v "$NODE_BIN" >/dev/null 2>&1 || { echo "[nodesplat] Node.js >= 22 not found; set NODESPLAT_NODE_BIN" >&2; exit 1; }

# In the ZIP the batch launcher lives under opensplat-ls6/.
export NODESPLAT_LAUNCHER="$ROOT/opensplat-ls6/tapisjob_app.sh"
cd "$ROOT"
exec "$NODE_BIN" "$ROOT/NodeSplat/index.js"
