# OpenSplat LS6 ZIP runtime

The ZIP runtime starts `tapisjob_app.sh` under a TACC Apptainer-enabled LS6 job. It expects
the OpenSplat binary at `/opt/opensplat/bin/opensplat` inside the selected CPU or CUDA SIF.

The runtime uses `--cleanenv --containall --no-home`; input is bound read-only at its canonical
host path and only the per-job Scratch run directory is writable. The OpenSplat container does
not receive Tapis credentials.

Build and inspect the package locally:

```bash
SKIP_UPLOAD=1 ./build-zip.sh
unzip -t opensplat-ls6.zip
```

The package does not register a Tapis app or submit a job. Those are separate, explicitly
approved operations after the CPU and CUDA SIFs and an LS6 fixture run have been reviewed.
