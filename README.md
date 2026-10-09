# OpenSplat LS6

Standalone Tapis/LS6 packaging for [WebODM/OpenSplat](https://github.com/WebODM/OpenSplat).
This package follows the existing `nodeodm-ls6` deployment pattern—Tapis ZIP runtime,
Apptainer, Scratch-backed job state, shared filesystem inputs, and archived outputs—but
OpenSplat is launched as a batch CLI and is not registered with ClusterODM.

## Input contract

The first version accepts an absolute directory containing an ODX/OpenSfM project. The
project must contain either:

```text
project/
  opensfm/
    reconstruction.json
    image_list.txt
```

or the equivalent `reconstruction.json` and `image_list.txt` directly at its root. The
reconstruction must contain exactly one reconstruction with non-empty cameras, shots, and
sparse points. Every image listed in `image_list.txt` must resolve to a file in the project,
either through a project-relative path or through the project’s `/var/www/data/<project-id>`
container path.

At runtime, the project is copied into the Tapis job working directory using the NodeODM
layout `opensplat_workdir/runtime/data/<project-id>`. Symlinks are dereferenced during this
copy, so an `images/` link into a WebODM or NodeODM import directory is materialized before
Apptainer starts. Absolute metadata paths using `/var/www/data/<project-id>` remain valid
because the runtime directory is bound at `/var/www`.

Raw images alone are not sufficient; ODX/OpenSfM must have already produced camera poses and
sparse points.

## Outputs

Each job selects one format:

```text
opensplat-<job-id>.ply
opensplat-<job-id>.splat
```

The job also publishes a log, preflight report, and provenance manifest. Run separate jobs to
produce both `.ply` and `.splat`; the launcher does not pretend that one OpenSplat invocation
creates both formats.

## Build and local validation

The ZIP contains the launcher and validators but not the OpenSplat SIF. CPU and CUDA SIFs are
separate, pinned artifacts prepared for LS6. Build the package without uploading:

```bash
cd opensplat-ls6
SKIP_UPLOAD=1 ./build-zip.sh
```

The app manifest uses a GPU-backed queue so `profile=cuda` cannot silently run without an
allocated NVIDIA device. The CPU profile is still available for functional smoke testing on
that node; it is not a CPU performance baseline. The app defaults to the CPU SIF at
`/corral/utexas/BCS26030/NodeODX/opensplat-cpu.sif` and uses the CUDA SIF for `profile=cuda`
at `/corral/utexas/BCS26030/NodeODX/opensplat-cuda.sif`. Those files must be built and
accepted on Linux/LS6 before a Tapis job can pass. This reuses the quota-capable Corral root
used by the NodeODX app; uploads must run with effective group `G-829114`.

## Direct LS6 CUDA smoke test

`test-opensplat-cuda.sbatch` uses the same single-node settings as the interactive test:
`PT2050-DataX`, `gpu-a100-dev`, 16 CPUs, and two hours. It expects the CUDA SIF to have already
been staged under `$SCRATCH`; it does not run apt, sudo, or a network pull inside the job.

Submit from an LS6 login node:

```bash
cd /path/to/opensplat-ls6
sbatch test-opensplat-cuda.sbatch
```

The default project is the NodeODX run used for bring-up. Override it, or reduce/increase the
smoke-test iterations, without editing the script:

```bash
sbatch --export=ALL,OPENSPLAT_PROJECT=/scratch/your/project,OPENSPLAT_ITERATIONS=100 \
  test-opensplat-cuda.sbatch
```

The Slurm `.out`/`.err` files remain beside the script. The detailed log, version probe, SIF
checksum, and `.ply` output are written to:

```text
$SCRATCH/opensplat-ls6/test-runs/<SLURM_JOB_ID>/
```

## Tapis arguments

The job arguments are, in order: `input_path`, `output_format` (`ply` or `splat`),
`num_iterations` (default `2000`), `profile` (`cpu` or `cuda`), and `center` (`0` preserves
the input CRS, `1` requests `--center`).

`OPENSPLAT_IMPORT_PATH_ROOTS` is an allowlist. The launcher canonicalizes the input path and
rejects traversal or symlink escapes, then copies the project into the job working directory
and validates the staged copy. Apptainer binds the staged NodeODM-style runtime at `/var/www`;
OpenSplat never reads the original symlinked input tree.

## Register and submit the app

The package is a Tapis batch app, not a NodeODM HTTP node. Registration is intentionally
separate from ZIP creation and requires an explicit write flag:

```bash
cd opensplat-ls6
python3 tapis/register_app.py --dry-run
python3 tapis/register_app.py --check
python3 tapis/register_app.py --create --confirm-external-write
```

The first two commands are non-mutating. The final command creates the exact app version from
`app.json` and refuses to overwrite that version if it already exists. Set `TAPIS_USERNAME` and
`TAPIS_PASSWORD`, or answer the prompts; credentials are not included in the ZIP.

After registration, submit a Tapis job with the positional arguments
`input_path`, `output_format`, `num_iterations`, `profile`, and `center`. The request must use
the registered app's `appId`/`appVersion`, `execSystemId=ls6`, and a GPU-backed queue such as
`gpu-a100-small`; the launcher then selects the CPU or CUDA SIF from `profile`. A submission
example should use a real allowlisted LS6 project path and should be treated as a separate,
explicitly approved external write.

## Acceptance record

Record the Tapis job UUID, app/version, OpenSplat commit/version, the exact values from
`images/opensplat-pins.env` plus the accepted SIF build manifest, container/SIF checksum,
queue/allocation/Slurm node, input project identity, CLI arguments, artifact validation results,
output hashes, exit code, and cleanup result.

No Tapis registration, upload, deployment, or production mutation is performed by the build
script unless `SKIP_UPLOAD=0` is explicitly set in a separately approved environment.
