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

The ZIP contains the launcher and validators but not the large OpenSplat runtime image. At job
startup, the launcher pulls the selected mutable OCI tag (`:cpu` or `:cuda`) with Apptainer and
materializes it as a SIF in a Scratch cache. Build the package without uploading:

```bash
cd opensplat-ls6
SKIP_UPLOAD=1 ./build-zip.sh
```

The app manifest uses a GPU-backed queue and fixes the registered workflow to CUDA. The image
build still publishes separate `:cpu` and `:cuda` tags for diagnostics and future CPU testing;
the registered app pulls `docker://ghcr.io/in-for-disaster-analytics/opensplat-ls6:cuda`.
The selected tag is refreshed on every job, then the resulting SIF is atomically placed under
`$SCRATCH/opensplat-ls6/sifs/`. The job manifest records both the OCI reference and final SIF
checksum. Set `OPENSPLAT_REFRESH_SIF=0` to reuse an existing cache, or set
`OPENSPLAT_SIF_PATH` for an explicit diagnostic override.

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

The registered app exposes two arguments: `input_path` and `num_iterations` (default `2000`).
The app runs the CUDA profile, writes a `.ply`, and preserves the input CRS (`center=0`). The
launcher retains `OPENSPLAT_OUTPUT_FORMAT`, `OPENSPLAT_PROFILE`, and `OPENSPLAT_CENTER` as
environment overrides for controlled local diagnostics, but they are not part of the public
Tapis app contract.

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

After registration, submit a Tapis job with the positional arguments `input_path` and
`num_iterations`. The request must use the registered app's `appId`/`appVersion` (`0.1.1`),
`execSystemId=ls6`, and a GPU-backed queue such as `gpu-a100-small`; the launcher pulls the
CUDA OCI image and produces a `.ply` artifact.
The compute node therefore needs outbound access to the OCI registry and enough Scratch space
for the SIF. A submission example should use a real allowlisted LS6 project path and should be
treated as a separate, explicitly approved external write.

## Acceptance record

Record the Tapis job UUID, app/version, OpenSplat commit/version, the exact values from
`images/opensplat-pins.env` plus the accepted SIF build manifest, container/SIF checksum,
queue/allocation/Slurm node, input project identity, CLI arguments, artifact validation results,
output hashes, exit code, and cleanup result.

No Tapis registration, upload, deployment, or production mutation is performed by the build
script unless `SKIP_UPLOAD=0` is explicitly set in a separately approved environment.

## Candidate: prepare WebODM assets on LS6

The local candidate launcher also accepts a directory containing `webodm-input.json`.
Candidate app 0.2.0 is deployed for testing; preparation passed on LS6. App 0.1.1 remains available.
The operator must create an immutable directory containing these files (photos must be
materialized beneath it; escaping symlinks are rejected):

```text
input/
  webodm-input.json
  cameras.json
  shots.geojson
  cloud.laz
  images/photo.jpg
```

```json
{
  "schema_version": 1,
  "input_format": "webodm-assets",
  "task_id": "WEBODM-TASK-UUID",
  "cameras_path": "cameras.json",
  "shots_path": "shots.geojson",
  "point_cloud_path": "cloud.laz",
  "images": [{"filename": "photo.jpg", "path": "images/photo.jpg"}],
  "rtc_offset": [0, 0],
  "image_size": 1920
}
```

Use the actual RTC offset from the task's `odm_georeferencing/coords.txt` or
`odm_georeferencing_model_geo.txt`, second line, first two values. Zero is correct only
when the source task uses zero. Include every registered shot's JPEG. The point cloud
must contain nonempty XYZ and RGB data in the same coordinate frame as the shots.
`image_size=0` keeps original dimensions. Metadata and cloud paths are relative to input/.

Provide `OPENSPLAT_PREPARE_SIF` and its exact `OPENSPLAT_PREPARE_SHA256`. The preparation
image recipe is `images/Dockerfile.prepare`; it is separate from CUDA training. Its Linux build and LS6 preparation checks passed; training acceptance remains pending. Preparation
runs with source assets and application scripts mounted read-only, writes COLMAP files
in job-local storage, and must finish before training begins. Default timeout is 7200
seconds (`OPENSPLAT_PREPARE_SECONDS`); input/output byte limit defaults to 1 TiB
(`OPENSPLAT_MAX_INPUT_BYTES`), with a separate per-output-file ceiling controlled by
`OPENSPLAT_MAX_PREPARE_FILE_KIB`. Job filesystem quota remains necessary to bound peak
Scratch usage. An input directory containing both manifest and OpenSfM reconstruction
is rejected. Legacy OpenSfM jobs do not require a preparation SIF.

The candidate package defaults to `opensplat-ls6-webodm-candidate.zip`; do not upload it
over the deployed package, register over 0.1.1, or replace production image tags.
Choose a new app version and version-specific package/image references for release.
There is no automatic WebODM submission or result attachment in this milestone.
After an approved LS6 run, upload the PLY through WebODM's Splats dialog and check
alignment against the same task's point cloud. Logs/provenance record preparation,
input checksums, RTC offset, and both preparation and training runtime identities.

The local Docker build ran out of space; GitHub Actions built the image successfully,
and LS6 preparation verification passed.


## Isolated deployment candidate (2026-10-28)

Candidate app spec: `app.candidate.json`, version 0.2.0. The deployed 0.1.1 app
is retained. Preparation image build:
https://github.com/In-For-Disaster-Analytics/opensplat-ls6/actions/runs/40746945717

The preparation image published successfully for linux/amd64 with OCI digest
`sha256:4c011c3e8b6e7c0a18e0a89b69d6e7d2c64b3df29e147e3599744b130a18e4c1`.
SIF conversion/verification runs on an LS6 compute node, following TACC policy.
Do not run Apptainer on login nodes.

Registration accepts `TAPIS_ACCESS_TOKEN` in the process environment, or the existing
username/password flow. Tokens must never be committed or included in ZIP inputs.
Use `python3 tapis/register_app.py --spec app.candidate.json --check` before
`--create --confirm-external-write`. Register only after its SIF SHA256 has been
filled from the verified runtime; the preparation launcher rejects missing hashes.


Candidate 0.2.0 is now registered. LS6 preparation was verified on a 38-photo
snapshot: 25,665 training points, about 11 seconds conversion at 1920 image size.
This supersedes the earlier unverified-runtime note. The candidate preparation SIF
SHA256 is `df64554a7481bfc1bd77521a2c4f9cd0f8ae505e51dcf3b7779eb059d396566a`.
Existing 0.1.1 remains available. Training and visual alignment have not yet been
accepted; no automatic WebODM submission is provided.

## NodeSplat worker packaging

`app.nodesplat.json` is a distinct candidate app (`nodesplat-ls6` 0.1.0) that runs the NodeSplat
worker (see `NodeSplat/`) instead of the batch launcher; published `opensplat-ls6` versions are
unchanged. `nodesplat_entry.sh` is its ZIP entry point and `build-nodesplat-zip.sh` builds
`nodesplat-ls6-candidate.zip` with `NodeSplat/` and `opensplat-ls6/` trees. Neither
script uploads or registers anything. Setting `OPENSPLAT_STREAM_LOG=1` makes `tapisjob_app.sh` stream
trainer output to stdout (via `tee`) while still writing the batch log and preserving the trainer's
exit status. The Node.js >= 22 location on LS6 is deployment-specific (`NODESPLAT_NODE_BIN`).
