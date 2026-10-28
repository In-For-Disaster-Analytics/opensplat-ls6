# Prepare WebODM task inputs in the OpenSplat LS6 app

## Status
Implementing

## Objective
Move WebODM-to-COLMAP preparation into the existing OpenSplat batch application, before training. Preserve the working OpenSfM input path.

## User need
Avoid generating and transferring a training ZIP on the WebODM server. Reuse photos and processed assets visible on shared storage. This milestone implements app-side preparation; automatic WebODM submission and result attachment are a subsequent milestone.

## Current code/system summary
The app at version 0.1.1 takes input_path and num_iterations. stage_project.py copies an OpenSfM project, and validate_project.py requires reconstruction.json and image_list.txt. The CUDA image does not explicitly install Python conversion dependencies or PDAL. WebODM 3.3.1 app/splats.py exports camera calibration, poses, JPEG images, and sampled georeferenced points. app/geoutils.py reads a horizontal RTC offset from georeferencing files; the viewer restores it. Existing OpenSplat files have uncommitted changes that must be preserved. DSO architecture docs at the prescribed /Volumes location are unavailable; no production storage mapping has been verified.

## Proposed design
Begin with a bounded dependency check of PDAL plus Python/NumPy/Pillow against the existing CUDA image. Record results and select the preparation runtime before implementing launcher integration. This checkpoint must not publish images or submit jobs.

The operator creates a manual input directory for this milestone, with webodm-input.json at its root, cameras.json, shots.geojson, cloud.laz, and images/<filename>. Manifest paths refer to those relative locations; rtc_offset is copied from the source task's georeferencing metadata. Validate this example against an actual task before acceptance. Automated manifest creation in WebODM is deferred. Select manifest mode only when webodm-input.json exists; reject a directory that also contains a legacy reconstruction.json at its root or under opensfm/. Otherwise use the existing legacy detector. Candidate version selection is a release-time decision.

Snapshot identity comprises manifest SHA256 plus each referenced file's relative path, size, nanosecond modification time, and SHA256 of its staged copy. Compare source size and modification time before and after copying and fail on detected changes; this detects ordinary concurrent edits but is not an atomic filesystem snapshot. Require an immutable input directory for acceptance.

For deterministic fixtures, compare camera and pose float64 values to WebODM with absolute tolerance 1e-9, point coordinates with tolerance 1e-6 in input coordinate units, exact RGB values, and exact resized dimensions. In LS6 acceptance, record at least three recognizable features in matching point-cloud/splat views and screenshots; record measured displacement in the task CRS and agree the dataset-specific tolerance before calling alignment accepted.

Keep the two positional arguments. input_path may identify a legacy OpenSfM directory or a directory containing a versioned WebODM manifest. Reject ambiguous inputs. Proposed manifest fields: schema_version=1, input_format=webodm-assets, task_id, cameras_path, shots_path, point_cloud_path, images (explicit filename/path pairs), rtc_offset (two finite numbers), and image_size (0 means original size). Use project-relative paths under the submitted directory; do not accept arbitrary absolute file references. The submitted directory may be an approved shared-storage task directory; no ZIP is needed. How task photos are materialized beneath that directory must be verified before production use.

Add a standalone converter derived from the pinned WebODM exporter, with upstream revision and license attribution. Remove Django/Task dependencies through an explicit input adapter. Preserve camera mapping, pose quaternion conventions, horizontal offsets, RGB conversion, sampling behavior, and image resizing. Require usable cameras, poses, referenced JPEGs, and a nonempty colored point cloud; reject missing images and unknown camera references rather than silently dropping them. Write COLMAP images/ and sparse/0/*.bin into the job workspace; never modify source assets. Preserve center=0 during training.

Validate manifest paths, symlinks, counts, and sizes before staging. Resolve every referenced file beneath approved source roots; reject traversal and escaping symlinks. Copy only required assets for manifest inputs instead of the entire task directory. Enforce limits before copying and after preparation. Preserve the legacy OpenSfM branch while avoiding new unsafe path behavior.

Package Python, NumPy, Pillow, and PDAL in a reproducible preparation runtime. Prefer extending the existing image only after dependency compatibility is checked; a separately pinned preparation image is the fallback if PDAL conflicts with CUDA/LibTorch. Run preparation inside Apptainer with read-only staged inputs and writable task-local output. Use checked subprocess arguments and explicit exit handling. Record source task, input format, manifest digest, RTC offset, resizing, source/exporter revision, point counts, runtime identity, and preparation duration in provenance. Never embed tokens.

Publish a new candidate app version and version-specific ZIP/image references for later approval; do not overwrite the deployed 0.1.1 package or mutable production image tags. Local implementation and tests do not upload, register, submit jobs, or change production.

## Files likely affected
opensplat-ls6: tapisjob_app.sh, stage_project.py, validate_project.py, new prepare_webodm.py, tests/test_validators.py and converter fixtures/tests, images/Dockerfile.cuda and Dockerfile.cpu if shared preparation runtime is selected, build-zip.sh, app.json, README.md, README-ZIP.md, and images/README.md. WebODM exporter is a read-only reference in this milestone.

## API/schema changes
Add a documented versioned input manifest. Retain legacy positional argument semantics. Choose the candidate app version after inspecting registration helper assumptions. No database schema or WebODM HTTP API changes.

## Data flow
Shared task assets + manifest -> path/size preflight -> selective staging -> app-side COLMAP conversion -> OpenSplat CUDA training -> validated PLY + provenance -> existing Tapis archive. Manual WebODM upload validates the first round trip.

## Risks and tradeoffs
Conversion still consumes time, and running it in a GPU allocation spends GPU queue time before training. PDAL packaging may conflict with the current runtime. Invalid coordinate handling can produce plausible but misaligned results. Source files can change during staging; record a snapshot identity and fail on detected changes. Actual Corral visibility and cross-user permissions remain acceptance requirements. Import-path allowlisting alone does not establish user authorization; the later submission service must enforce task ownership and allocation. Local tests cannot prove LS6 runtime compatibility.

## Alternatives considered
WebODM training ZIP: already works but retains preparation load and duplicate transfer. Original OpenSfM reconstruction: supported today but depends on retained backend workspaces. Separate CPU preparation job: better resource utilization but adds scheduling and orchestration; defer until preparation timings justify it. Automatic WebODM job submission now: defer until input preparation and alignment are proven.

## Test plan
Compare converter output against the pinned WebODM exporter using deterministic fixtures: cameras, poses, nonzero RTC offsets, point coordinates/colors, resized intrinsics, and COLMAP binary parsing. Exercise missing images, duplicate filenames, unsupported cameras, malformed/empty point clouds, traversal, symlink escapes, and input limits. Run existing legacy staging/validator tests. Mock Apptainer to verify preparation precedes training and errors prevent training/publication. Build candidate runtime and verify Python imports and PDAL CLI when tooling permits. Separately approved LS6 acceptance must train a representative dataset and manually import its PLY into the same WebODM task with correct point-cloud overlay.

## Documentation plan
Document manifest examples, exact file/path requirements, conversion settings, runtime dependencies, limits, manual acceptance, and candidate deployment/rollback. Update DSO architecture documentation when available before deployment.

## Rollout/rollback plan
Local code and tests first. Build candidate artifacts without publishing. After explicit external-write approval, publish/register a distinct candidate version, run LS6 acceptance, and retain deployed 0.1.1 unchanged. Roll back by selecting the old app/version; no source assets are altered. Automatic WebODM orchestration requires a separate approved design.

## Open questions
Verify a real task asset/image layout and equivalent LS6-visible paths. Confirm preparation dependency packaging and pinned OpenSplat COLMAP-reader behavior. Confirm candidate version and isolated archive paths before publication. Decide whether preparation duration warrants a CPU job after measurement.

## Decisions
### 2026-10-28 - Prepare inputs inside the batch app
- Decision: Reuse WebODM conversion semantics in a standalone app-side converter, retaining OpenSfM support.
- Reason: User wants to avoid WebODM-side training export work.
- Alternatives rejected: Requiring a downloaded ZIP as the only integration path.
- User feedback: User said “ok lets do it” after discussion of app-side preparation.
- Impact: Local preparation implementation is the intended scope; deployment and automatic submission are not yet approved.

## User feedback / decisions
User approved pursuing app-side conversion. This concrete input/runtime design is presented for review under the repository's Major-task approval gate.

### 2026-10-28 - Implementation approval and runtime isolation
- User approved the concrete design with “do it”.
- Architect and security reviewer support local implementation with selective staging, explicit limits, read-only inputs, and separate preparation runtime.
- Dependency probe in local WebODM image passed: PDAL 2.3.0, NumPy 1.26.2, Pillow 11.3.0. Use a separate preparation SIF; the local WebODM image is a test harness, not the deployment runtime. A minimal conda-forge preparation image is the candidate build recipe; Linux/LS6 acceptance remains required.

### 2026-10-28 - Local implementation and validation evidence
- Converter, manifest staging, launcher isolation, output preflight, attribution, docs, and candidate ZIP implemented. Existing uncommitted configuration edits preserved.
- PDAL conversion/resizing and preparation failure tests pass in the local WebODM runtime. Independent review found packaging attribution, writable parent mount, and copy-time byte-budget issues; corrected all three.
- Candidate image build attempted twice; Docker failed before dependency solving with “No space left on device”. No cleanup performed. Status remains Implementing pending runtime build validation.
- No deployed app changes, upload, registration, LS6 job, commit, or push.
- Remaining: Linux runtime build, real task path verification, LS6 training and alignment acceptance. Automatic WebODM submission remains deferred.
