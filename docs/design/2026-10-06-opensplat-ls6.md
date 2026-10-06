# OpenSplat on TACC LS6

Status: Implemented

## Objective

Define a reproducible Tapis/LS6 configuration for [WebODM/OpenSplat](https://github.com/WebODM/OpenSplat), using the existing NodeODM LS6 deployment conventions where they apply: ZIP packaging, Tapis batch execution, Apptainer on LS6, Scratch-backed runtime state, shared filesystem inputs, structured logs, and archived outputs.

The first milestone is a standalone OpenSplat LS6 workload that can be validated independently of the current NodeODM/ClusterODM and ODX migration paths.

## User need

- **Primary user:** ODM/ODX engineer or operator responsible for running photogrammetry workloads on TACC LS6.
- **Secondary users:** downstream researchers or services that consume Gaussian-splat scene files; the exact consumer is not yet specified.
- **Job-to-be-done:** provide a known OpenSplat build and LS6 launch configuration that accepts a documented reconstruction project, runs with predictable resource settings, and publishes usable scene artifacts.
- **Current pain:** OpenSplat has no configuration or launcher in this repository, while the existing LS6 infrastructure is centered on NodeODM and Tapis. The OpenSplat runtime, resource requirements, input contract, and output publication path have not yet been made reproducible on LS6.
- **Definition of success:** a reproducible LS6 Tapis job runs OpenSplat against a representative ODX/OpenSfM/COLMAP-compatible project, produces the requested scene files, records the exact source/build/runtime provenance, and archives logs and artifacts without modifying the working NodeODM deployment.

## Current code/system summary

- `nodeodm-ls6/` provides the reference LS6 Tapis ZIP application. Its manifest uses the `ls6` execution system, Apptainer scheduler profile, Tapis job-name requirements for TAP, shared Scratch/Corral paths, and archived job output.
- The NodeODM launcher starts a long-lived HTTP service inside Apptainer, registers it with ClusterODM, and supports task lifecycle, shared `import_path`, checkpoints, and cleanup. Those service-specific behaviors are not directly provided by OpenSplat.
- `nodeodx-ls6/` is an isolated newer ODX/NodeODX path. Its design spec explicitly treats OpenSplat as a separate workstream and leaves the OpenSplat repository/API contract unresolved.
- OpenSplat is a portable C++ Gaussian-splatting CLI. Its upstream README documents CPU and GPU builds, requires OpenCV and LibTorch, accepts ODX/OpenSfM/COLMAP/OpenMVG/nerfstudio project formats with sparse points, and can emit `.ply`, `.splat`, `.spz`, or `.rad` scene files. It documents a CLI shape equivalent to `opensplat <project> -n <iterations>` and `-o <output>` for compressed splat output.
- The current repository contains no OpenSplat source checkout, LS6 app manifest, build script, Tapis app registration, or downstream output contract.

## Proposed design

Create a new isolated `opensplat-ls6/` package modeled on the packaging and operational safeguards of `nodeodm-ls6/`, with a CLI-oriented execution model.

### Runtime boundary

“Configure like NodeODM” means reuse the LS6/Tapis/Apptainer/shared-storage deployment pattern, not that OpenSplat must be made into a NodeODM HTTP node. The first version is a standalone Tapis batch app and does not register with ClusterODM.

The first version will:

1. Receive either Tapis-staged input or an allowlisted shared `import_path` to an existing reconstruction project.
2. Validate that the input project is under an approved path and contains the minimum sparse-reconstruction files required by the selected OpenSplat reader.
3. Launch a pinned OpenSplat executable inside an Apptainer runtime on LS6.
4. Select CPU or NVIDIA GPU execution explicitly through the app configuration; do not silently claim GPU support until an LS6 GPU acceptance run passes.
5. Write task-local working data and logs under Scratch, with group-compatible permissions for shared Corral outputs.
6. Emit a deterministic output inventory, including the requested scene format, file size, checksum, OpenSplat version, source commit, build/runtime metadata, input path, and Tapis job UUID.
7. Archive outputs and logs through the Tapis job configuration without changing NodeODM or ClusterODM production behavior.

### Build and image strategy

The initial implementation will use a pinned Linux OpenSplat source commit and a reproducible Apptainer image or build artifact, rather than depending on an unpinned `latest` image.

The design will compare two supported build paths:

- build OpenSplat and its LibTorch/OpenCV dependencies into a versioned LS6-compatible image/artifact; or
- consume a maintained upstream/container build only if its source commit, CUDA/LibTorch versions, and runtime libraries can be pinned and verified.

The acceptance artifact must record the OpenSplat commit, compiler/toolchain, LibTorch version, OpenCV version, CUDA version when applicable, container digest or SIF checksum, and CMake configuration. macOS builds are non-authoritative.

### Initial resource profile

Start with one LS6 node and a GPU-backed queue profile analogous to the existing NodeODM app, while retaining a CPU profile for functional smoke testing on the allocated GPU node. The initial Tapis manifest uses `gpu-a100-small` so a CUDA job cannot silently run without an NVIDIA allocation. Exact GPU model, memory, iteration count, and walltime remain subject to LS6 acceptance.

CPU and NVIDIA builds are separate artifacts. The CPU profile uses `GPU_RUNTIME=CPU` and CPU LibTorch; the NVIDIA profile uses CUDA-enabled LibTorch, explicit CUDA architecture settings, and Apptainer GPU passthrough. A CPU pass does not imply GPU readiness.

The app manifest should expose only the controls needed for reproducible runs, initially:

- input project path or staged input;
- one output format per job (`ply` or `splat`; later formats only after validation). OpenSplat's documented CLI selects an output filename; the launcher must not claim that one invocation produces both formats. The acceptance suite runs separate jobs for `.ply` and `.splat`.
- training iteration count;
- optional center/resume controls supported by the pinned OpenSplat build;
- CPU/GPU execution profile;
- memory, walltime, and queue profile through Tapis app metadata rather than ad hoc shell overrides.

The first app is intentionally GPU-backed for a single queue-safe contract. A later CPU-only app may be registered if CPU throughput testing justifies a separate Tapis profile.

### Relationship to ODX and NodeODM

The first milestone consumes an already-generated reconstruction project. It does not replace ODX, does not alter NodeODM, and does not require WebODM or ClusterODM changes.

Later integration may add an ODX post-processing stage or a NodeODX/ClusterODX adapter, but that is a separate milestone after the standalone LS6 CLI contract passes and is outside this implementation.

## Files likely affected

New files, following the existing LS6 package convention:

- `opensplat-ls6/app.json` — Tapis ZIP app definition, queues, resource profile, arguments, and archive behavior.
- `opensplat-ls6/tapisjob_app.sh` — Tapis entrypoint, input validation, Apptainer launch, logging, output publication, and cleanup.
- `opensplat-ls6/build-zip.sh` — reproducible ZIP creation and local archive verification.
- `opensplat-ls6/README.md` and/or `opensplat-ls6/README-ZIP.md` — build, registration, submission, input/output, and acceptance instructions.
- `opensplat-ls6/opensplat-source/` or a pinned image/build manifest — only if source is bundled or built as part of the package.
- `opensplat-ls6/tests/` — shell/configuration checks and fixture-level output validation.

Existing design documentation:

- `docs/design/2026-10-06-odx-tacc-ls6-migration.md` — add a cross-reference and final Splat milestone status after this design is approved.

Architecture documentation may need updates after implementation only if a new Tapis app, production URL, queue, authentication flow, or integration endpoint is adopted.

## API/schema changes

No existing HTTP API or database schema changes are proposed for the standalone milestone.

The Tapis job contract must define:

- accepted input forms and the required reconstruction-project layout;
- allowlisted shared-path roots and traversal/symlink policy;
- CLI options and their defaults;
- output formats and filenames;
- exit-code and failure semantics;
- provenance/acceptance-manifest fields.

If later work requires WebODM/ClusterODM to submit or monitor OpenSplat directly, that should introduce a versioned adapter/API design rather than pretending the CLI is NodeODM-compatible.

## Data flow

```text
Tapis job submission
  -> LS6 ZIP runtime
    -> validate staged input or allowlisted shared reconstruction path
      -> Apptainer OpenSplat executable
        -> Scratch task workspace
          -> .ply/.splat/.spz/.rad + logs + provenance manifest
            -> Tapis archive / approved Corral output
```

The first input contract is an existing ODX project containing a readable reconstruction with camera poses, sparse points, and image references. The launcher must reject ambiguous or missing layouts rather than guessing among submodels. Raw images alone are not sufficient for the first OpenSplat contract unless a separate reconstruction stage is added.

## Risks and tradeoffs

- **CLI versus NodeODM service:** OpenSplat is not an HTTP task service, so direct ClusterODM registration would require a new wrapper and lifecycle contract. The standalone batch boundary is simpler and keeps the first acceptance test honest.
- **GPU portability:** CUDA, LibTorch, compiler, and GPU architecture must match. A CPU fallback exists upstream but is substantially slower, so CPU success cannot imply production GPU readiness.
- **Input compatibility:** OpenSplat requires sparse reconstruction data and may accept different formats with different file requirements. The launcher must validate the selected format and fail clearly when files are missing.
- **ODX layout ambiguity:** A project may contain multiple submodels, missing `opensfm/reconstruction.json`, stale image paths, or no sparse points. The preflight validator must select one explicit project root or reject the input with a diagnostic; it must not silently choose a submodel.
- **Output-mode semantics:** `.ply` and `.splat` are explicit output modes. Separate jobs are required unless a later, validated conversion step is introduced.
- **Artifact size and publication:** `.ply` and compressed formats have different downstream tradeoffs. Outputs should be written atomically and checksummed before archival.
- **Build provenance:** An unpinned image or dependency stack could make LS6 results irreproducible. Source, dependency, image/SIF, and configuration pins are acceptance requirements.
- **Queue/resource mismatch:** A CUDA runtime on a CPU queue can fail late or produce misleading smoke results. The initial manifest restricts the queue filter to GPU queues and records queue/allocation in the manifest.
- **Storage/security:** Shared filesystem inputs require canonical-path validation and protection against traversal or symlink escape. Outputs must remain task-local until validated.
- **Scope drift:** Adding WebODM UI, ClusterODM scheduling, or ODX pipeline changes before the CLI pass would broaden the task and obscure whether the runtime itself works.

## Alternatives considered

- **Make OpenSplat a NodeODM-compatible HTTP node immediately:** not recommended for the first milestone because OpenSplat is currently a CLI and the wrapper would introduce a new task API, service lifecycle, registration, and cancellation surface.
- **Add OpenSplat directly into the current ODX/NodeODX migration:** not recommended because the migration spec is already implementing a separate ODX vertical slice and explicitly leaves Splat as an optional workstream.
- **Run only through a container tagged `latest`:** rejected for acceptance because it prevents reliable provenance and rollback.
- **Support raw images as the first input:** deferred because upstream OpenSplat documents project-format inputs with camera poses and sparse points; raw-image reconstruction would duplicate or depend on ODX/OpenSfM behavior.
- **Use CPU only:** useful for an initial functional probe, but insufficient as the production target if LS6 GPU throughput is required.
- **Use one universal CPU/GPU artifact:** rejected because OpenSplat's build configuration, LibTorch package, CUDA architecture, and runtime libraries differ between CPU and CUDA profiles.

## Test plan

### Design and packaging checks

- Validate `app.json` JSON syntax and Tapis-required fields.
- Build the ZIP with uploads disabled and verify its complete file list.
- Check that no credentials or tokens are embedded in the ZIP or emitted by the launcher.
- Run shell syntax and static checks for the entrypoint and helper scripts.

### Runtime checks on LS6

- Confirm the selected CPU and GPU queues expose the expected Apptainer, CUDA, and filesystem capabilities.
- Run `opensplat --help` and record version/build metadata.
- Run a small known-good ODX fixture through the CPU profile and verify preflight acceptance.
- Run the same or a representative fixture through the NVIDIA profile when the selected LS6 GPU queue is available.
- Run separate jobs for `.ply` and `.splat`; verify non-empty files, format-aware structure checks, checksums, and valid output inventory.
- Verify missing-input, unsupported-format, invalid-path, insufficient-space, and process-failure behavior.
- Verify output publication is atomic and logs remain available after completion.
- If resume is enabled, test resume only from a compatible pinned OpenSplat output; otherwise keep resume out of the first milestone.

### Acceptance record

Every accepted run must record the Tapis job UUID, app ID/version, OpenSplat commit/version, build configuration, container/SIF digest, LS6 queue and allocation, input project identity, CLI arguments, output inventory, checksums, status/exit code, and cleanup result.

## Documentation plan

- Document the standalone batch boundary and explicitly distinguish it from NodeODM/ClusterODM.
- Document input project layouts, shared-path rules, CLI arguments, output formats, and example Tapis submissions.
- Document CPU/GPU support separately and record known LS6 queue/resource requirements.
- Document build/image provenance and the acceptance-manifest format.
- Cross-link the final design and acceptance status from the ODX/LS6 migration documentation.
- Update DSO architecture pages only after the deployed app ID, storage path, queue, and integration behavior are verified.

## Rollout/rollback plan

1. Keep the current NodeODM/ClusterODM deployment and the ODX migration path unchanged.
2. Build and validate OpenSplat in a separate `opensplat-ls6/` package and non-production Tapis app/version.
3. Use a dedicated test output path and non-production/approved allocation settings.
4. Accept the CPU smoke path before claiming functional compatibility; accept the GPU path separately.
5. Only after standalone acceptance, decide whether to add an ODX post-processing hook or a NodeODX/ClusterODX adapter.
6. Roll back by disabling the OpenSplat Tapis app/version and retaining the existing NodeODM/ODX paths. No existing task output should be overwritten by a failed Splat run.

No Tapis registration, upload, deployment, GitHub push, or production mutation is authorized by this draft.

## Open questions

- Should the first app be CPU-only for bring-up, GPU-first, or expose both profiles from the beginning?
- Which LS6 queue/GPU type and allocation should be the authoritative acceptance target?
- Which OpenSplat source commit or release should be pinned?
- Should the package build OpenSplat on LS6, consume a project-owned container/SIF, or use an upstream container after provenance review?
- Which input format is the first acceptance target: ODX, OpenSfM, or COLMAP?
- Which output formats are required for downstream use: `.ply`, `.splat`, `.spz`, `.rad`, or more than one?
- Is a standalone Tapis batch app sufficient for the first milestone, or is ClusterODM/WebODM submission required immediately?
- Is resumable training required for the first version?
- Which Corral/Tapis storage location and allocation should receive the ZIP and archived outputs?

## Decisions

### 2026-10-06 - Treat OpenSplat as a separate LS6 workstream

- **Decision:** Create a separate OpenSplat LS6 design and package rather than folding it into the implementing ODX migration spec.
- **Reason:** The existing migration already identifies OpenSplat as optional and has a separate runtime/API contract to resolve.
- **Alternatives rejected:** Adding an undefined Splat stage to the ODX migration or modifying NodeODM in place.
- **User feedback:** User identified `https://github.com/WebODM/OpenSplat` as the target and asked for an LS6 configuration analogous to NodeODM.
- **Impact on implementation:** The design targets a new `opensplat-ls6/` package and leaves existing NodeODM/NodeODX code unchanged.

### 2026-10-06 - Use a CLI batch boundary for the first milestone

- **Decision:** Treat OpenSplat as a standalone Tapis batch CLI for initial LS6 acceptance.
- **Reason:** Upstream OpenSplat exposes a C++ command-line workflow rather than the NodeODM HTTP/task API.
- **Alternatives rejected:** Immediate ClusterODM registration and a new HTTP wrapper, which would add a larger unvalidated service contract.
- **User feedback:** User approved the standalone Tapis batch boundary by saying “do it” after reviewing the design defaults.
- **Impact on implementation:** The launcher will validate inputs, run OpenSplat under Apptainer, publish artifacts, and archive provenance without ClusterODM registration.

### 2026-10-06 - Separate build profiles and output modes

- **Decision:** Use distinct CPU and NVIDIA runtime artifacts, and expose one explicit output format per job; validate `.ply` and `.splat` through separate acceptance runs.
- **Reason:** OpenSplat selects GPU runtime at build time, and its documented `-o` option selects the output filename rather than guaranteeing multiple formats from one invocation.
- **Alternatives rejected:** A universal CPU/GPU artifact and an implicit single-run dual-output contract.
- **User feedback:** User approved CPU smoke plus NVIDIA GPU acceptance and `.ply` plus `.splat` outputs; this decision makes those approvals operationally testable.
- **Impact on implementation:** `app.json` and the launcher will carry explicit profile/output parameters; output validation and manifests will record the selected mode.

### 2026-10-06 - Approve the standalone LS6 implementation scope

- **Decision:** User approved implementation of the standalone Tapis batch app with an existing ODX project as input, separate CPU and NVIDIA acceptance profiles, `.ply` and `.splat` output modes, and pinned build/runtime artifacts.
- **Reason:** This is the smallest useful LS6 milestone that follows the NodeODM deployment pattern while respecting OpenSplat's CLI boundary.
- **Alternatives rejected:** Immediate WebODM/ClusterODM integration and production Tapis mutation.
- **User feedback:** User said “do it” after reviewing the draft and defaults.
- **Impact on implementation:** Create only the isolated `opensplat-ls6/` package and local validation; defer registration, upload, deployment, and downstream service changes.

### 2026-10-06 - Make the first Tapis profile GPU-backed

- **Decision:** Use `gpu-a100-small` as the initial app queue and restrict the manifest queue filter to GPU queues; keep `profile=cpu` as a functional smoke mode on the allocated GPU node.
- **Reason:** A CUDA profile must not be schedulable onto a CPU-only queue. A later CPU-only Tapis app can be added without weakening the CUDA contract.
- **Alternatives rejected:** Leaving `vm-small` as the default while relying on the launcher to discover GPU availability.
- **User feedback:** This is a QA-driven implementation refinement within the user's approved CPU-plus-NVIDIA scope.
- **Impact on implementation:** `app.json` now enforces a GPU-backed queue, and tests assert the queue/resource contract.

### 2026-10-06 - Record complete runtime provenance and validate artifacts before publication

- **Decision:** Include app/version, Tapis job, source commit, build metadata, SIF SHA256, queue/allocation, output hashes, format validation, and cleanup policy in the generated manifest; strengthen PLY and SPLAT structural checks before atomic publication.
- **Reason:** Local QA identified incomplete provenance and validators that could accept truncated or arbitrary outputs.
- **Alternatives rejected:** Existence/non-empty checks alone and documenting provenance without emitting it per run.
- **User feedback:** This is a QA-driven implementation refinement within the approved design.
- **Impact on implementation:** The launcher and validators carry the acceptance evidence needed for later LS6 review.

### 2026-10-06 - Complete the isolated local implementation without external execution

- **Decision:** Mark the package implementation complete after local validation, while leaving SIF construction, Tapis registration/upload, job submission, and LS6 CPU/CUDA acceptance as a separate approved follow-up.
- **Reason:** Those steps mutate external state or require the authoritative Linux/LS6 runtime and were not executed from the local macOS workspace.
- **Alternatives rejected:** Treating ZIP creation or local validator tests as evidence of LS6 runtime compatibility.
- **User feedback:** User approved implementation by saying “do it”; no external execution approval was given.
- **Impact on implementation:** The spec is `Implemented`; the remaining acceptance gates are documented as open questions/follow-up rather than hidden in the local result.

## User feedback / decisions

- 2026-10-06: User specified the upstream WebODM/OpenSplat repository and requested an LS6 configuration patterned after the existing NodeODM configuration.
- 2026-10-06: User approved the standalone Tapis batch boundary, ODX project input, CPU smoke plus NVIDIA acceptance, `.ply` and `.splat` output modes, and pinned build/runtime strategy.
- 2026-10-06: Local implementation and validation completed. LS6 SIF build, Tapis registration/submission, and CPU/CUDA fixture acceptance remain explicitly pending and are not claimed by this implementation.
