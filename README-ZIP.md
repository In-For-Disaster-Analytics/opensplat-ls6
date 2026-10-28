# OpenSplat LS6 ZIP runtime

The ZIP runtime starts `tapisjob_app.sh` under a TACC Apptainer-enabled LS6 job. It pulls the
selected CPU or CUDA OCI tag into a Scratch SIF cache at startup, then expects the OpenSplat
binary at `/opt/opensplat/bin/opensplat` inside that SIF.

The runtime uses `--cleanenv --containall --no-home`. It copies the allowlisted input project
into `opensplat_workdir/runtime/data/<project-id>` using the NodeODM layout, dereferences
symlinks, validates the staged project, and binds that runtime at `/var/www`. The OpenSplat
container does not receive Tapis credentials or access the original input tree.

Build and inspect the package locally:

```bash
SKIP_UPLOAD=1 ./build-zip.sh
unzip -t opensplat-ls6.zip
```

The package does not register a Tapis app or submit a job. Those are separate, explicitly
approved operations after the OCI tags and an LS6 fixture run have been reviewed. The runtime
requires outbound access from the compute node to GHCR unless an explicit
`OPENSPLAT_SIF_PATH` override is supplied.

For the registration workflow, run `python3 tapis/register_app.py --dry-run` from the source
checkout. The helper is not part of the runtime ZIP; it supports read-only `--check` and guarded
`--create --confirm-external-write` modes against the Tapis tenant. This interface change is
version `0.1.1`; do not try to overwrite an existing immutable `0.1.0` registration.

The WebODM preparation candidate uses `opensplat-ls6-webodm-candidate.zip` by default.
It includes converter/manifest modules and license attribution. Keep this separate
from the deployed ZIP and register a new app version only after approved acceptance.
See README.md for its operator-created input manifest and separate preparation SIF.
