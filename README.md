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
sparse points. Every image listed in `image_list.txt` must resolve beneath the project root.

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
`/corral/utexas/BCS26030/OpenSplat/opensplat-cpu.sif` and uses the CUDA SIF for `profile=cuda`
at `/corral/utexas/BCS26030/OpenSplat/opensplat-cuda.sif`. Those files must be built and
accepted on Linux/LS6 before a Tapis job can pass.

## Tapis arguments

The job arguments are, in order: `input_path`, `output_format` (`ply` or `splat`),
`num_iterations` (default `2000`), `profile` (`cpu` or `cuda`), and `center` (`0` preserves
the input CRS, `1` requests `--center`).

`OPENSPLAT_IMPORT_PATH_ROOTS` is an allowlist. The launcher canonicalizes the input path and
rejects traversal or symlink escapes. It binds the input read-only and binds only a job-owned
Scratch directory writable.

## Acceptance record

Record the Tapis job UUID, app/version, OpenSplat commit/version, the exact values from
`images/opensplat-pins.env` plus the accepted SIF build manifest, container/SIF checksum,
queue/allocation/Slurm node, input project identity, CLI arguments, artifact validation results,
output hashes, exit code, and cleanup result.

No Tapis registration, upload, deployment, or production mutation is performed by the build
script unless `SKIP_UPLOAD=0` is explicitly set in a separately approved environment.
