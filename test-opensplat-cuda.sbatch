#!/usr/bin/env bash
#SBATCH -A PT2050-DataX
#SBATCH -p gpu-a100-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH -t 02:00:00
#SBATCH -J opensplat-cuda-test
#SBATCH -o opensplat-cuda-%j.out
#SBATCH -e opensplat-cuda-%j.err

# TACC's Apptainer module sources bash completion code that is not nounset-safe.
# Keep fail-fast and pipefail enabled, but disable only nounset during module load.
set -eo pipefail
set +u
module load tacc-apptainer
set -u

# Override these with --export or by editing the values before submission.
PROJECT=${OPENSPLAT_PROJECT:-/scratch/06659/wmobley/nodeodx_3493593/runtime/data/f7c58ac9-da06-497b-84b5-e07f9224f1bb}
SIF=${OPENSPLAT_CUDA_SIF:-${SCRATCH}/opensplat-ls6/images/opensplat-cuda.sif}
ITERATIONS=${OPENSPLAT_ITERATIONS:-100}
CENTER=${OPENSPLAT_CENTER:-0}
PROJECT_ID=${PROJECT##*/}
CONTAINER_PROJECT=${OPENSPLAT_CONTAINER_PROJECT:-/var/www/data/${PROJECT_ID}}

JOB_ID=${SLURM_JOB_ID}
SOURCE_PROJECT=${PROJECT}
PROJECT=${SCRATCH}/opensplat-ls6/test-inputs/${PROJECT_ID}-${JOB_ID}
RUN_DIR=${SCRATCH}/opensplat-ls6/test-runs/${JOB_ID}
OUTPUT=${RUN_DIR}/opensplat-${JOB_ID}.ply
VERSION=${RUN_DIR}/opensplat-version.txt

mkdir -p "${RUN_DIR}"
exec > >(tee -a "${RUN_DIR}/opensplat-${JOB_ID}.log") 2>&1

echo "[opensplat-test] job=${JOB_ID}"
echo "[opensplat-test] host=$(hostname)"
echo "[opensplat-test] project=${PROJECT}"
echo "[opensplat-test] source_project=${SOURCE_PROJECT}"
echo "[opensplat-test] container_project=${CONTAINER_PROJECT}"
echo "[opensplat-test] sif=${SIF}"
echo "[opensplat-test] iterations=${ITERATIONS}"

[[ -d "${SOURCE_PROJECT}" ]] || { echo "ERROR: project directory not found: ${SOURCE_PROJECT}" >&2; exit 1; }
[[ -d "${SOURCE_PROJECT}/images" ]] || { echo "ERROR: project images directory not found: ${SOURCE_PROJECT}/images" >&2; exit 1; }
[[ -r "${SIF}" ]] || { echo "ERROR: CUDA SIF not readable: ${SIF}" >&2; exit 1; }
[[ "${ITERATIONS}" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "ERROR: OPENSPLAT_ITERATIONS must be 1-999999" >&2; exit 1; }
[[ "${CENTER}" == 0 || "${CENTER}" == 1 ]] || { echo "ERROR: OPENSPLAT_CENTER must be 0 or 1" >&2; exit 1; }

echo '--- GPU ---'
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
echo '--- Apptainer ---'
apptainer --version
echo '--- SIF ---'
ls -lh "${SIF}"
sha256sum "${SIF}"

echo '--- Staging project to Scratch ---'
mkdir -p "${PROJECT}"
cp -aL "${SOURCE_PROJECT}/." "${PROJECT}/"
[[ -d "${PROJECT}/images" ]] || { echo "ERROR: staged images directory not found: ${PROJECT}/images" >&2; exit 1; }
[[ ! -L "${PROJECT}/images" ]] || { echo "ERROR: staged images directory is still a symlink: ${PROJECT}/images" >&2; exit 1; }
IMAGE_COUNT=$(find "${PROJECT}/images" -maxdepth 1 -type f | wc -l)
[[ "${IMAGE_COUNT}" -gt 0 ]] || { echo "ERROR: staged images directory is empty: ${PROJECT}/images" >&2; exit 1; }
echo "[opensplat-test] staged_image_files=${IMAGE_COUNT}"
du -sh "${PROJECT}"

APPTAINER=(
  apptainer exec
  --nv
  --cleanenv
  --containall
  --no-home
  --env "PATH=/opt/opensplat/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  --env "LD_LIBRARY_PATH=/opt/libtorch-cuda/lib:/opt/opensplat/lib"
  --bind "${PROJECT}:${CONTAINER_PROJECT}:ro"
  --bind "${PROJECT}/images:${CONTAINER_PROJECT}/images:ro"
  --bind "${RUN_DIR}:${RUN_DIR}:rw"
)

"${APPTAINER[@]}" "${SIF}" /opt/opensplat/bin/opensplat --version | tee "${VERSION}"

ARGS=(
  "${CONTAINER_PROJECT}"
  --output "${OUTPUT}"
  --num-iters "${ITERATIONS}"
)
if [[ "${CENTER}" == 1 ]]; then
  ARGS+=(--center)
fi

echo '--- OpenSplat command ---'
printf '%q ' "${APPTAINER[@]}" "${SIF}" /opt/opensplat/bin/opensplat "${ARGS[@]}"
printf '\n'

if "${APPTAINER[@]}" "${SIF}" /opt/opensplat/bin/opensplat "${ARGS[@]}"; then
  :
else
  OPEN_SPLAT_STATUS=$?
  echo "ERROR: OpenSplat exited with status ${OPEN_SPLAT_STATUS}"
  echo "Diagnostic log: ${RUN_DIR}/opensplat-${JOB_ID}.log"
  exit "${OPEN_SPLAT_STATUS}"
fi

[[ -s "${OUTPUT}" ]] || { echo "ERROR: OpenSplat did not create a non-empty output" >&2; exit 1; }

echo '--- Result ---'
ls -lh "${OUTPUT}"
sha256sum "${OUTPUT}"
echo "[opensplat-test] PASS: ${OUTPUT}"
