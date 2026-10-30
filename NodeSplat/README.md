# NodeSplat

A single-run OpenSplat worker with a deliberate subset of the NodeODX task API. ClusterODX
starts one NodeSplat per training attempt inside an LS6 GPU Tapis job and proxies its console
to WebODM. It is not a general task runner: it executes only the fixed
`opensplat-ls6/tapisjob_app.sh` launcher against an already-prepared WebODM snapshot.

Status: local implementation. Registration of the Tapis app, deployment and real GPU runs are
separate, approved steps (see the NodeSplat design spec in the odm-suite `docs/design/` directory).

## API (all routes require `Authorization: Bearer <NODESPLAT_API_CAPABILITY>`)

| Route | Notes |
|---|---|
| `GET /info` | `engine: nodesplat`, `capabilities: [opensplat-webodm-v1]`, concurrency 1, run/task/job/profile identity |
| `GET /options` | `num_iterations` (1–1000, default 100), `image_size` (0 or 16–4096, default 1920) |
| `POST /task/new` | JSON `{run_id, source_task_id, manifest_sha256, settings, "set-uuid"}`; identity must match the allocation. Replays of identical input are idempotent, different input is 409 |
| `GET /task/:uuid/info` | NodeODX numeric status (10/20/30/40/50) plus `phase`, `progress`, `error`, `result_ready` |
| `GET /task/:uuid/output?line=N` | JSON array of console lines, max 500 lines / 256 KiB per page |
| `POST /task/cancel` | Idempotent; SIGTERM to the process group, SIGKILL after 10 s |
| `POST /task/remove` | Terminal tasks only; logical removal, never deletes archives |
| `GET /task/:uuid/download/{model.ply,manifest.json,console.txt}` | Fixed allowlist. Model/manifest only after `result_ready` |

Not supported: image upload, URL fetch, arbitrary paths or executables, restart (a new attempt
is a new run).

## Configuration (environment, injected by ClusterODX / `nodesplat_entry.sh`)

Required: `NODESPLAT_ENABLED=YES`, `NODESPLAT_RUN_ID`, `NODESPLAT_CLUSTER_TASK_ID`,
`NODESPLAT_TAPIS_JOB_ID`, `NODESPLAT_PROFILE_ID`, `NODESPLAT_APP_ID`, `NODESPLAT_APP_VERSION`,
`NODESPLAT_BIND_HOST`, `NODESPLAT_PORT`, `NODESPLAT_PUBLIC_URL` (`http(s)://host:port/`, path must
be `/`; its host and port are what ClusterODX is told to connect to), `NODESPLAT_CALLBACK_URL`
(ClusterODX base URL; the worker appends `/webhook/register-node`),
`NODESPLAT_API_CAPABILITY` (the node token ClusterODX presents to this worker; 43–128 chars of
`[A-Za-z0-9_-]`; it is unique to this job and also authenticates the registration), `NODESPLAT_INPUT_ROOT`, `NODESPLAT_OUTPUT_ROOT`, `NODESPLAT_WORK_ROOT`
(absolute paths) and `NODESPLAT_LEASE_DEADLINE` (epoch seconds, must be in the future).
Optional bounds: `NODESPLAT_MAX_LOG_BYTES` (default and maximum 50 MiB),
`NODESPLAT_MAX_INPUT_BYTES`, `NODESPLAT_MAX_IMAGES`, `NODESPLAT_MAX_RESULT_BYTES`, `NODESPLAT_LAUNCHER` (absolute path; defaults to `../tapisjob_app.sh`).
There are no production port or address defaults.

## Lifecycle

1. Starts and registers with ClusterODX through the same webhook NodeODX workers use:
   `POST <NODESPLAT_CALLBACK_URL>/webhook/register-node` with no `Authorization` header and a JSON
   body `{hostname, port, token, tapisJobUuid, registrationUuid, role: "nodesplat",
   nodeReady: true}`. `token` is `NODESPLAT_API_CAPABILITY`, `tapisJobUuid` is the Tapis job UUID and
   `registrationUuid` is the ClusterODX task UUID. Redirects are refused and each attempt times out
   after 10 s. The registration is repeated every 30 s (a ClusterODX restart drops its in-memory route),
   and a failed attempt is simply retried on the next tick.
2. ClusterODX then `POST /task/new`. The worker validates the manifest checksum/schema and every
   asset (regular files, no symlinks, byte/image bounds).
3. Preparation and training run through the launcher with a scrubbed environment (no
   capabilities, grants, cluster secrets or user tokens). Console output is redacted, bounded and
   persisted to `<output root>/<run>/console.txt`.
4. Exit 0 plus provenance/SHA-256 validation publishes `model.ply` and `manifest.json`
   atomically. ClusterODX sees `result_ready` by polling `GET /task/:uuid/info`.
5. Handoff: after ClusterODX verifies the artifacts it calls `POST /task/remove`, and the worker exits.
   If that never happens, the worker exits after a 10 minute grace period once the task is terminal,
   and on the lease deadline it cancels any running child and exits.
   A worker restart with a non-terminal record fails the attempt; it never retrains.

## Tests and packaging

```bash
npm test                              # node --test, fake launcher scripts, no GPU
../build-nodesplat-zip.sh   # builds the candidate ZIP; uploads nothing
```
