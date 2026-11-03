#!/usr/bin/env bash
# Tapis ZIP entry point for the NodeSplat app. ClusterODX injects the per-job NODESPLAT_* values; everything
# here is derived from the Tapis job or from operator-set variables, never from user input.
#
# NODESPLAT_RUN_MODE=container (default): like NodeODX, run the worker INSIDE one image that holds Node.js,
#   Python/PDAL and OpenSplat. The host only needs bash + apptainer. The image is pulled once and cached.
# NODESPLAT_RUN_MODE=host: run the worker from this ZIP with a Node.js >= 22 binary on the host
#   (NODESPLAT_NODE_BIN); the launcher then starts its own Apptainer containers.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")" && pwd)
fail() { echo "[nodesplat] ERROR: $*" >&2; exit 1; }
: "${_tapisJobUUID:?_tapisJobUUID is required}"
: "${_tapisJobWorkingDir:?_tapisJobWorkingDir is required}"
: "${NODESPLAT_PORT:?NODESPLAT_PORT is required}"

export NODESPLAT_TAPIS_JOB_ID="$_tapisJobUUID"
export NODESPLAT_WORK_ROOT="${NODESPLAT_WORK_ROOT:-$_tapisJobWorkingDir/nodesplat-work}"
mkdir -p "$NODESPLAT_WORK_ROOT"
# The address ClusterODX can reach; override when the compute node name is not routable.
export NODESPLAT_PUBLIC_URL="${NODESPLAT_PUBLIC_URL:-http://$(hostname -f):$NODESPLAT_PORT}"

MODE=${NODESPLAT_RUN_MODE:-container}
case "$MODE" in container|host) ;; *) fail "NODESPLAT_RUN_MODE must be container or host" ;; esac

if [[ "$MODE" == "host" ]]; then
  NODE_BIN=${NODESPLAT_NODE_BIN:-node}
  command -v "$NODE_BIN" >/dev/null 2>&1 || fail "Node.js >= 22 not found; set NODESPLAT_NODE_BIN or use NODESPLAT_RUN_MODE=container"
  # In the ZIP the batch launcher lives under opensplat-ls6/.
  export NODESPLAT_LAUNCHER="$ROOT/opensplat-ls6/tapisjob_app.sh"
  cd "$ROOT"
  exec "$NODE_BIN" "$ROOT/NodeSplat/index.js"
fi

# ---- container mode --------------------------------------------------------------------------
if ! command -v apptainer >/dev/null 2>&1 && command -v module >/dev/null 2>&1; then
  module load tacc-apptainer || true
fi
command -v apptainer >/dev/null 2>&1 || fail "apptainer not found"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum not found"

IMAGE=${NODESPLAT_IMAGE:-docker://ghcr.io/in-for-disaster-analytics/opensplat-ls6:nodesplat}
[[ "$IMAGE" =~ ^docker://[A-Za-z0-9._/@:+-]{1,255}$ ]] || fail "NODESPLAT_IMAGE must be a docker:// reference"

CACHE=${NODESPLAT_SIF_CACHE_DIR:-${SCRATCH:-$_tapisJobWorkingDir}/nodesplat/sifs}
mkdir -p "$CACHE"
SIF="$CACHE/nodesplat-$(printf '%s' "$IMAGE" | sha256sum | cut -c1-16).sif"
# A digest-pinned reference never changes, so a cached copy is always right. A moving tag is re-pulled
# only when asked (NODESPLAT_REFRESH_SIF=1), so routine runs do not pay the multi-GB pull each time.
if [[ ! -s "$SIF" || ( "$IMAGE" != *@sha256:* && "${NODESPLAT_REFRESH_SIF:-0}" == "1" ) ]]; then
  PULL_TMP="$CACHE/.$(basename "$SIF").$_tapisJobUUID.tmp"
  echo "[nodesplat] pulling $IMAGE"
  apptainer pull --force "$PULL_TMP" "$IMAGE" || { rm -f -- "$PULL_TMP"; fail "failed to pull $IMAGE"; }
  [[ -s "$PULL_TMP" ]] || fail "pull produced an empty image"
  mv -f -- "$PULL_TMP" "$SIF"
fi
IMAGE_SHA256=$(sha256sum -- "$SIF" | awk '{print $1}')

# --cleanenv drops the host environment, so pass exactly what the worker and launcher need.
PASS=$(compgen -e | grep -E '^(NODESPLAT_|OPENSPLAT_|_tapis|SLURM_JOB_|SCRATCH$|CUDA_VISIBLE_DEVICES$)' || true)
for name in $PASS; do export "APPTAINERENV_$name=${!name}"; done
export APPTAINERENV_NODESPLAT_IN_CONTAINER=1
export APPTAINERENV_NODESPLAT_IMAGE_REF="$IMAGE"
export APPTAINERENV_NODESPLAT_IMAGE_SHA256="$IMAGE_SHA256"

BINDS=(--bind "$_tapisJobWorkingDir:$_tapisJobWorkingDir:rw")
[[ -n "${NODESPLAT_INPUT_ROOT:-}" ]] && BINDS+=(--bind "$NODESPLAT_INPUT_ROOT:$NODESPLAT_INPUT_ROOT:ro")
[[ -n "${NODESPLAT_OUTPUT_ROOT:-}" ]] && BINDS+=(--bind "$NODESPLAT_OUTPUT_ROOT:$NODESPLAT_OUTPUT_ROOT:rw")
case "$NODESPLAT_WORK_ROOT/" in "$_tapisJobWorkingDir"/*) ;; *) BINDS+=(--bind "$NODESPLAT_WORK_ROOT:$NODESPLAT_WORK_ROOT:rw") ;; esac

echo "[nodesplat] starting the worker in $IMAGE (sha256 ${IMAGE_SHA256:0:12})"
exec apptainer exec --nv --cleanenv --containall --no-home "${BINDS[@]}" "$SIF" /opt/node/bin/node /opt/nodesplat/NodeSplat/index.js
