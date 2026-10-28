#!/bin/bash
#SBATCH -A PT2050-DataX
#SBATCH -p development
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 16
#SBATCH -t 00:20:00
#SBATCH -J opensplat-convert-test
#SBATCH -o /scratch/06659/wmobley/opensplat-ls6/candidates/webodm-0.2.0/convert-%j.out
#SBATCH -e /scratch/06659/wmobley/opensplat-ls6/candidates/webodm-0.2.0/convert-%j.err
set -eo pipefail
module load tacc-apptainer/1.4.1
set -u
root=/scratch/06659/wmobley/opensplat-ls6/candidates/webodm-0.2.0
run="$root/verification-$SLURM_JOB_ID"
mkdir -p "$run/app" "$run/colmap"
unzip -q "$root/opensplat-ls6-webodm-candidate.zip" -d "$run/app"
python3 "$run/app/stage_project.py" --source "$root/input" --destination "$run/input" --container-project /input --max-images 100 --max-bytes 1073741824 > "$run/snapshot.json"
timeout 900 apptainer exec --cleanenv --containall --no-home --bind "$run/input:/input:ro" --bind "$run/colmap:/prepared:rw" --bind "$run/app:/app:ro" "$root/prepare-node.sif" python /app/prepare_webodm.py --project /input --output /prepared > "$run/preparation.json"
python3 "$run/app/validate_colmap.py" "$run/colmap" --max-bytes 1073741824
cat "$run/preparation.json"
printf 'WEBODM_CONVERSION_VERIFIED\n'
