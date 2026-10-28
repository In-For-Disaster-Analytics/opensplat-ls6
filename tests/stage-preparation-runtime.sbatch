#!/bin/bash
#SBATCH -A PT2050-DataX
#SBATCH -p gpu-a100-dev
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH -t 00:30:00
#SBATCH -J opensplat-prep-stage
#SBATCH -o /scratch/06659/wmobley/opensplat-ls6/candidates/webodm-0.2.0/stage-%j.out
#SBATCH -e /scratch/06659/wmobley/opensplat-ls6/candidates/webodm-0.2.0/stage-%j.err
set -eo pipefail
module load tacc-apptainer/1.4.1
set -u
root=/scratch/06659/wmobley/opensplat-ls6/candidates/webodm-0.2.0
export APPTAINER_CACHEDIR="$root/cache"
export APPTAINER_TMPDIR="$(mktemp -d /tmp/opensplat-preparation.XXXXXXXX)"
export APPTAINER_MKSQUASHFS_PROCS=4
apptainer pull "$root/prepare-node.sif" docker://ghcr.io/in-for-disaster-analytics/opensplat-ls6@sha256:4c011c3e8b6e7c0a18e0a89b69d6e7d2c64b3df29e147e3599744b130a18e4c1
apptainer exec --cleanenv --containall --no-home "$root/prepare-node.sif" pdal --version
apptainer exec --cleanenv --containall --no-home "$root/prepare-node.sif" python -c 'import numpy, PIL; print(numpy.__version__, PIL.__version__)'
sha256sum "$root/prepare-node.sif" > "$root/prepare-node.sha256"
sg G-829114 -c "install -m 0640 '$root/prepare-node.sif' /corral/utexas/BCS26030/NodeODX/candidates/webodm-0.2.0/prepare-node.sif"
printf 'PREPARATION_RUNTIME_READY\n'
