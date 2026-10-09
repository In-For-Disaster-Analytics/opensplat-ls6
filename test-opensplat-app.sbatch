#!/usr/bin/env bash
# Validate the Tapis ZIP runtime itself on LS6 before submitting through the Tapis API.
# This is a one-shot app-runtime smoke test, not a NodeODM/ClusterODM service test.
#SBATCH -A PT2050-DataX
#SBATCH -p gpu-a100-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH -t 02:00:00
#SBATCH -J opensplat-app-smoke
#SBATCH -o opensplat-app-%j.out
#SBATCH -e opensplat-app-%j.err

set -eo pipefail
set +u
module load tacc-apptainer
set -u

PROJECT=${OPENSPLAT_PROJECT:-/scratch/06659/wmobley/nodeodx_3493593/runtime/data/f7c58ac9-da06-497b-84b5-e07f9224f1bb}
SIF=${OPENSPLAT_CUDA_SIF:-${SCRATCH}/opensplat-ls6/images/opensplat-cuda.sif}
ZIP=${OPENSPLAT_RUNTIME_ZIP:-${SCRATCH}/opensplat-ls6/opensplat-ls6.zip}
ITERATIONS=${OPENSPLAT_ITERATIONS:-100}
CENTER=${OPENSPLAT_CENTER:-0}

JOB_ID=${SLURM_JOB_ID}
RUN_DIR=${SCRATCH}/opensplat-ls6/app-smoke/${JOB_ID}
APP_DIR=${RUN_DIR}/runtime
OUTPUT_DIR=${RUN_DIR}/output
mkdir -p "${APP_DIR}" "${OUTPUT_DIR}"
exec > >(tee -a "${RUN_DIR}/opensplat-app-${JOB_ID}.log") 2>&1

echo "[opensplat-app-smoke] job=${JOB_ID} host=$(hostname)"
echo "[opensplat-app-smoke] project=${PROJECT}"
echo "[opensplat-app-smoke] sif=${SIF}"
echo "[opensplat-app-smoke] zip=${ZIP}"

[[ -d "${PROJECT}/images" ]] || { echo "ERROR: project/images not found: ${PROJECT}" >&2; exit 1; }
[[ -r "${SIF}" ]] || { echo "ERROR: CUDA SIF not readable: ${SIF}" >&2; exit 1; }
[[ -r "${ZIP}" ]] || { echo "ERROR: runtime ZIP not readable: ${ZIP}" >&2; exit 1; }
[[ "${ITERATIONS}" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "ERROR: invalid iterations" >&2; exit 1; }
[[ "${CENTER}" == 0 || "${CENTER}" == 1 ]] || { echo "ERROR: invalid center" >&2; exit 1; }

unzip -q "${ZIP}" -d "${APP_DIR}"
[[ -x "${APP_DIR}/tapisjob_app.sh" ]] || chmod 0750 "${APP_DIR}/tapisjob_app.sh"

export OPENSPLAT_CPU_SIF_PATH="${SIF}"
export OPENSPLAT_CUDA_SIF_PATH="${SIF}"
export OPENSPLAT_BINARY=/opt/opensplat/bin/opensplat
export OPENSPLAT_APP_ID=opensplat-ls6
export OPENSPLAT_APP_VERSION=0.1.0
export OPENSPLAT_SOURCE_COMMIT=effe9e5dbe6d7f672ecd7f4c59a6c1cf879d916f
export OPENSPLAT_BUILD_METADATA="LS6 app-runtime smoke; CUDA SIF sha256=$(sha256sum "${SIF}" | awk '{print $1}')"
export OPENSPLAT_IMPORT_PATH_ROOTS=/scratch/06659/wmobley
export OPENSPLAT_MAX_INPUT_BYTES=1099511627776
export OPENSPLAT_MAX_IMAGES=20000
export _tapisJobUUID="opensplat-app-smoke-${JOB_ID}"
export _tapisJobWorkingDir="${RUN_DIR}"
export _tapisExecSystemOutputDir="${OUTPUT_DIR}"
export _tapisExecSystemLogicalQueue="${SLURM_JOB_PARTITION}"

"${APP_DIR}/tapisjob_app.sh" "${PROJECT}" ply "${ITERATIONS}" cuda "${CENTER}"

echo '--- app smoke result ---'
find "${OUTPUT_DIR}" -maxdepth 1 -type f -printf '%f %s bytes\n' | sort
echo "[opensplat-app-smoke] PASS: ${OUTPUT_DIR}"
