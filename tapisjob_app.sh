#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
umask 027

log() { printf '[opensplat-ls6] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

safe_job_id() {
  local raw=${1:-local-job}
  raw=${raw//[^A-Za-z0-9._-]/_}
  printf '%s' "${raw:0:120}"
}

is_below_root() {
  local path=$1 root=$2
  [[ "$path" == "$root" || "$path" == "$root"/* ]]
}

resolve_allowed_path() {
  local candidate=$1 roots=${OPENSPLAT_IMPORT_PATH_ROOTS:-}
  [[ "$candidate" = /* ]] || fail "input_path must be an absolute path"
  [[ -n "$roots" ]] || fail "OPENSPLAT_IMPORT_PATH_ROOTS is empty"

  local canonical
  canonical=$(realpath -e -- "$candidate") || fail "input_path does not exist: $candidate"
  [[ -d "$canonical" ]] || fail "input_path is not a directory: $canonical"

  local root canonical_root
  while IFS= read -r root; do
    [[ -n "$root" ]] || continue
    canonical_root=$(realpath -e -- "$root" 2>/dev/null || true)
    [[ -n "$canonical_root" ]] || continue
    if is_below_root "$canonical" "$canonical_root"; then
      printf '%s' "$canonical"
      return 0
    fi
  done < <(tr ':' '\n' <<< "$roots")
  fail "input_path is outside the configured allowlist"
}

INPUT_PATH=${1:-${OPENSPLAT_INPUT_PATH:-${_tapisExecSystemInputDir:-}}}
OUTPUT_FORMAT=${2:-${OPENSPLAT_OUTPUT_FORMAT:-ply}}
NUM_ITERATIONS=${3:-${OPENSPLAT_NUM_ITERATIONS:-2000}}
PROFILE=${4:-${OPENSPLAT_PROFILE:-cpu}}
CENTER=${5:-${OPENSPLAT_CENTER:-0}}

[[ -n "$INPUT_PATH" ]] || fail "input_path is required"
case "$OUTPUT_FORMAT" in
  ply|splat) ;;
  *) fail "output_format must be ply or splat" ;;
esac
case "$PROFILE" in
  cpu) SIF_PATH=${OPENSPLAT_CPU_SIF_PATH:-} ;;
  cuda) SIF_PATH=${OPENSPLAT_CUDA_SIF_PATH:-} ;;
  *) fail "profile must be cpu or cuda" ;;
esac
[[ "$NUM_ITERATIONS" =~ ^[1-9][0-9]{0,5}$ ]] || fail "num_iterations must be an integer from 1 to 999999"
[[ "$CENTER" == "0" || "$CENTER" == "1" ]] || fail "center must be 0 or 1"
[[ -n "$SIF_PATH" ]] || fail "no SIF configured for profile=$PROFILE"

require_command realpath
require_command python3
require_command sha256sum
require_command apptainer

JOB_ID=$(safe_job_id "${_tapisJobUUID:-${SLURM_JOB_ID:-local-job}}")
WORK_ROOT=${_tapisJobWorkingDir:-$PWD}
OUTPUT_DIR=${_tapisExecSystemOutputDir:-$WORK_ROOT/output}
WORK_DIR_BASE="$WORK_ROOT/opensplat_workdir"
RUNTIME_DIR="$WORK_DIR_BASE/runtime"
RUN_DIR="$WORK_DIR_BASE/runs/$JOB_ID"
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR" "$RUNTIME_DIR/data" "$RUNTIME_DIR/tmp" "$RUNTIME_DIR/logs" "$OUTPUT_DIR"

INPUT_CANONICAL=$(resolve_allowed_path "$INPUT_PATH")
PROJECT_ID=${INPUT_CANONICAL##*/}
STAGED_CONTAINER_PROJECT="/var/www/data/$PROJECT_ID"
STAGED_PROJECT="$RUNTIME_DIR/data/$PROJECT_ID"
[[ -f "$SIF_PATH" ]] || fail "configured SIF does not exist: $SIF_PATH"
[[ -r "$SIF_PATH" ]] || fail "configured SIF is not readable: $SIF_PATH"

STAGE_JSON="$RUN_DIR/stage.json"
python3 "$SCRIPT_DIR/stage_project.py" \
  --source "$INPUT_CANONICAL" \
  --destination "$STAGED_PROJECT" \
  --container-project "$STAGED_CONTAINER_PROJECT" \
  > "$STAGE_JSON"

PREFLIGHT_JSON="$RUN_DIR/preflight.json"
python3 "$SCRIPT_DIR/validate_project.py" \
  --project "$STAGED_PROJECT" \
  --container-project "$STAGED_CONTAINER_PROJECT" \
  --max-images "${OPENSPLAT_MAX_IMAGES:-20000}" \
  --max-bytes "${OPENSPLAT_MAX_INPUT_BYTES:-1099511627776}" \
  > "$PREFLIGHT_JSON"

OUTPUT_TMP="$RUN_DIR/scene.${OUTPUT_FORMAT}.tmp"
OUTPUT_FINAL="$OUTPUT_DIR/opensplat-${JOB_ID}.${OUTPUT_FORMAT}"
PUBLISH_TMP="$OUTPUT_DIR/.opensplat-${JOB_ID}.${OUTPUT_FORMAT}.tmp"
MANIFEST_TMP="$RUN_DIR/manifest.json.tmp"
MANIFEST_FINAL="$OUTPUT_DIR/opensplat-${JOB_ID}.manifest.json"
LOG_FILE="$OUTPUT_DIR/opensplat-${JOB_ID}.log"
VERSION_FILE="$RUN_DIR/opensplat-version.txt"

[[ ! -e "$OUTPUT_FINAL" && ! -e "$MANIFEST_FINAL" ]] || fail "refusing to overwrite existing output for job $JOB_ID"

APPTAINER_ARGS=(exec --cleanenv --containall --no-home)
if [[ "$PROFILE" == "cuda" ]]; then APPTAINER_ARGS+=(--nv); fi
APPTAINER_ARGS+=(
  --bind "$RUNTIME_DIR:/var/www:rw"
  --bind "$RUN_DIR:$RUN_DIR:rw"
)

OPEN_SPLAT_CMD=(
  apptainer "${APPTAINER_ARGS[@]}" "$SIF_PATH" "${OPENSPLAT_BINARY:-/opt/opensplat/bin/opensplat}"
  "$STAGED_CONTAINER_PROJECT" --output "$OUTPUT_TMP" --num-iters "$NUM_ITERATIONS"
)
if [[ "$PROFILE" == "cpu" ]]; then OPEN_SPLAT_CMD+=(--cpu); fi
if [[ "$CENTER" == "1" ]]; then OPEN_SPLAT_CMD+=(--center); fi

{
  printf 'profile=%s\nformat=%s\niterations=%s\nsource_input=%s\nstaged_input=%s\ncontainer_input=%s\n' "$PROFILE" "$OUTPUT_FORMAT" "$NUM_ITERATIONS" "$INPUT_CANONICAL" "$STAGED_PROJECT" "$STAGED_CONTAINER_PROJECT"
  apptainer "${APPTAINER_ARGS[@]}" "$SIF_PATH" "${OPENSPLAT_BINARY:-/opt/opensplat/bin/opensplat}" --version
} > "$VERSION_FILE" 2>&1 || fail "OpenSplat version probe failed; see $VERSION_FILE"

log "starting profile=$PROFILE format=$OUTPUT_FORMAT iterations=$NUM_ITERATIONS"
set +e
"${OPEN_SPLAT_CMD[@]}" > "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e
if [[ "$EXIT_CODE" -ne 0 ]]; then
  log "OpenSplat failed with exit code $EXIT_CODE; log=$LOG_FILE" >&2
  exit "$EXIT_CODE"
fi

python3 "$SCRIPT_DIR/validate_artifact.py" --format "$OUTPUT_FORMAT" --path "$OUTPUT_TMP" > "$RUN_DIR/artifact.json"
cp -- "$OUTPUT_TMP" "$PUBLISH_TMP"
python3 "$SCRIPT_DIR/validate_artifact.py" --format "$OUTPUT_FORMAT" --path "$PUBLISH_TMP" >/dev/null
mv -- "$PUBLISH_TMP" "$OUTPUT_FINAL"

export OPENSPLAT_INPUT_CANONICAL="$INPUT_CANONICAL"
export OPENSPLAT_INPUT_STAGED="$STAGED_PROJECT"
export OPENSPLAT_INPUT_CONTAINER="$STAGED_CONTAINER_PROJECT"
export OPENSPLAT_SIF_PATH="$SIF_PATH"
export OPENSPLAT_SIF_SHA256=$(sha256sum -- "$SIF_PATH" | awk '{print $1}')
export OPENSPLAT_TAPIS_JOB_UUID=${_tapisJobUUID:-}
export OPENSPLAT_QUEUE=${SLURM_JOB_PARTITION:-${_tapisExecSystemLogicalQueue:-}}
export OPENSPLAT_ALLOCATION=${SLURM_JOB_ACCOUNT:-${_tapisJobOwner:-}}
export OPENSPLAT_SLURM_JOB_ID=${SLURM_JOB_ID:-}
export OPENSPLAT_SLURM_NODELIST=${SLURM_NODELIST:-}
python3 - "$MANIFEST_TMP" "$OUTPUT_FINAL" "$RUN_DIR/artifact.json" "$PREFLIGHT_JSON" "$VERSION_FILE" "$PROFILE" "$OUTPUT_FORMAT" "$NUM_ITERATIONS" "$CENTER" "$JOB_ID" <<'PY'
import hashlib
import json
import os
import pathlib
import sys

manifest_path, output_path, artifact_path, preflight_path, version_path, profile, output_format, iterations, center, job_id = sys.argv[1:]

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

manifest = {
    "job_id": job_id,
    "tapis_job_uuid": os.environ.get("OPENSPLAT_TAPIS_JOB_UUID", ""),
    "app": {
        "id": os.environ.get("OPENSPLAT_APP_ID", "opensplat-ls6"),
        "version": os.environ.get("OPENSPLAT_APP_VERSION", "unknown"),
    },
    "source_commit": os.environ.get("OPENSPLAT_SOURCE_COMMIT", "unknown"),
    "build_metadata": os.environ.get("OPENSPLAT_BUILD_METADATA", "unknown"),
    "profile": profile,
    "output_format": output_format,
    "num_iterations": int(iterations),
    "center": center == "1",
    "input_project": os.environ["OPENSPLAT_INPUT_CANONICAL"],
    "staged_project": os.environ["OPENSPLAT_INPUT_STAGED"],
    "container_project": os.environ["OPENSPLAT_INPUT_CONTAINER"],
    "allocation": os.environ.get("OPENSPLAT_ALLOCATION", ""),
    "queue": os.environ.get("OPENSPLAT_QUEUE", ""),
    "slurm": {
        "job_id": os.environ.get("OPENSPLAT_SLURM_JOB_ID", ""),
        "node_list": os.environ.get("OPENSPLAT_SLURM_NODELIST", ""),
        "account": os.environ.get("OPENSPLAT_ALLOCATION", ""),
    },
    "runtime": {"sif_path": os.environ.get("OPENSPLAT_SIF_PATH", ""), "sif_sha256": os.environ.get("OPENSPLAT_SIF_SHA256", "")},
    "pins_file": "images/opensplat-pins.env",
    "output": {"path": os.path.abspath(output_path), "bytes": os.path.getsize(output_path), "sha256": sha256(output_path)},
    "artifact_validation": json.load(open(artifact_path, encoding="utf-8")),
    "project_preflight": json.load(open(preflight_path, encoding="utf-8")),
    "runtime_version": pathlib.Path(version_path).read_text(encoding="utf-8"),
    "cleanup": {"status": "preserved", "policy": "retain job-owned opensplat_workdir for diagnostics"},
}
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

cp -- "$MANIFEST_TMP" "$MANIFEST_FINAL"
cp -- "$PREFLIGHT_JSON" "$OUTPUT_DIR/opensplat-${JOB_ID}.preflight.json"
log "completed output=$OUTPUT_FINAL manifest=$MANIFEST_FINAL log=$LOG_FILE"
