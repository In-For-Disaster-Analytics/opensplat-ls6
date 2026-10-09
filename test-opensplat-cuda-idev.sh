#!/usr/bin/env bash
set -eo pipefail

# TACC's Apptainer module sources bash completion code that is not nounset-safe.
set +u
module load tacc-apptainer
set -u

SOURCE_PROJECT=${OPENSPLAT_SOURCE_PROJECT:-/scratch/06659/wmobley/nodeodx_3493593/runtime/data/f7c58ac9-da06-497b-84b5-e07f9224f1bb}
SIF=${OPENSPLAT_CUDA_SIF:-${SCRATCH}/opensplat-ls6/images/opensplat-cuda.sif}
ITERATIONS=${OPENSPLAT_ITERATIONS:-100}
CENTER=${OPENSPLAT_CENTER:-0}

SESSION_ID=${SLURM_JOB_ID:-idev-$$}
PROJECT_ID=${SOURCE_PROJECT##*/}
STAGE_ROOT=${SCRATCH}/opensplat-ls6/idev-inputs
PROJECT=${STAGE_ROOT}/${PROJECT_ID}-${SESSION_ID}
RUN_DIR=${SCRATCH}/opensplat-ls6/idev-runs/${SESSION_ID}
OUTPUT=${RUN_DIR}/opensplat-${SESSION_ID}.ply
VERSION=${RUN_DIR}/opensplat-version.txt
# OpenSplat reads image paths from the project metadata. This project was
# generated with the stable NodeODX container prefix below, so keep the
# container-side path stable even though the host-side staging copy is unique.
CONTAINER_PROJECT=/var/www/data/${PROJECT_ID}

mkdir -p "${PROJECT}" "${RUN_DIR}"
exec > >(tee -a "${RUN_DIR}/opensplat-${SESSION_ID}.log") 2>&1

echo "[opensplat-idev] session=${SESSION_ID}"
echo "[opensplat-idev] host=$(hostname)"
echo "[opensplat-idev] source=${SOURCE_PROJECT}"
echo "[opensplat-idev] staged_project=${PROJECT}"
echo "[opensplat-idev] container_project=${CONTAINER_PROJECT}"
echo "[opensplat-idev] sif=${SIF}"
echo "[opensplat-idev] iterations=${ITERATIONS}"

[[ -d "${SOURCE_PROJECT}" ]] || { echo "ERROR: source project directory not found: ${SOURCE_PROJECT}" >&2; exit 1; }
[[ -d "${SOURCE_PROJECT}/images" ]] || { echo "ERROR: source images directory not found: ${SOURCE_PROJECT}/images" >&2; exit 1; }
[[ -r "${SIF}" ]] || { echo "ERROR: CUDA SIF not readable: ${SIF}" >&2; exit 1; }
[[ "${ITERATIONS}" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "ERROR: OPENSPLAT_ITERATIONS must be 1-999999" >&2; exit 1; }
[[ "${CENTER}" == 0 || "${CENTER}" == 1 ]] || { echo "ERROR: OPENSPLAT_CENTER must be 0 or 1" >&2; exit 1; }

echo '--- Copying project to Scratch ---'
cp -aL "${SOURCE_PROJECT}/." "${PROJECT}/"
[[ -d "${PROJECT}/images" ]] || { echo "ERROR: staged images directory not found: ${PROJECT}/images" >&2; exit 1; }
[[ ! -L "${PROJECT}/images" ]] || { echo "ERROR: staged images directory is still a symlink: ${PROJECT}/images" >&2; exit 1; }
IMAGE_COUNT=$(find "${PROJECT}/images" -maxdepth 1 -type f | wc -l)
[[ "${IMAGE_COUNT}" -gt 0 ]] || { echo "ERROR: staged images directory is empty: ${PROJECT}/images" >&2; exit 1; }
echo "[opensplat-idev] staged_image_files=${IMAGE_COUNT}"
du -sh "${PROJECT}"

echo '--- GPU ---'
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
echo '--- Apptainer ---'
apptainer --version
echo '--- SIF ---'
ls -lh "${SIF}"
sha256sum "${SIF}"

APPTAINER=(
  apptainer exec
  --nv
  --cleanenv
  --containall
  --no-home
  --env "PATH=/opt/opensplat/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  --env "LD_LIBRARY_PATH=/opt/libtorch-cuda/lib:/opt/opensplat/lib"
  --bind "${PROJECT}:${CONTAINER_PROJECT}:ro"
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

"${APPTAINER[@]}" "${SIF}" /opt/opensplat/bin/opensplat "${ARGS[@]}"

[[ -s "${OUTPUT}" ]] || { echo "ERROR: OpenSplat did not create a non-empty output" >&2; exit 1; }

echo '--- Result ---'
ls -lh "${OUTPUT}"
sha256sum "${OUTPUT}"
echo "[opensplat-idev] PASS: ${OUTPUT}"
