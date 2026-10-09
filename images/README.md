# OpenSplat image and SIF build inputs

The Tapis ZIP deliberately does not contain a large compiler/runtime image. The repository's
GitHub Actions workflow builds and publishes two separate, self-contained OCI images from the
pins in `opensplat-pins.env`:

- `ghcr.io/in-for-disaster-analytics/opensplat-ls6:cpu`: `GPU_RUNTIME=CPU` with CPU LibTorch;
- `ghcr.io/in-for-disaster-analytics/opensplat-ls6:cuda`: CUDA 12.1.1, LibTorch 2.2.1, and an
  LS6 A100-compatible `CMAKE_CUDA_ARCHITECTURES=80`.

The upstream OpenSplat CMake configuration selects the GPU runtime at build time, so one SIF
must not be reused as both CPU and CUDA acceptance evidence. The upstream CUDA Dockerfile is a
useful reference for dependency installation and CMake flags. The CI images are build
artifacts, not the runtime contract: convert each public OCI tag to a SIF on LS6, record the
SIF checksum, and stage the accepted SIF at the Corral paths configured in `app.json`.

After the package is made public and the workflow succeeds, the LS6 staging commands are:

```bash
module load tacc-apptainer
mkdir -p "$SCRATCH/opensplat-ls6/images"
apptainer pull --force "$SCRATCH/opensplat-ls6/images/opensplat-cpu.sif" \
  docker://ghcr.io/in-for-disaster-analytics/opensplat-ls6:cpu
apptainer pull --force "$SCRATCH/opensplat-ls6/images/opensplat-cuda.sif" \
  docker://ghcr.io/in-for-disaster-analytics/opensplat-ls6:cuda
apptainer exec "$SCRATCH/opensplat-ls6/images/opensplat-cuda.sif" \
  /opt/opensplat/bin/opensplat --version
sha256sum "$SCRATCH/opensplat-ls6/images/"*.sif
```

The final accepted SIFs must then be copied to the Corral locations in `app.json` by the
approved staging workflow. Reuse `/corral/utexas/BCS26030/NodeODX` and run the copy with
effective group `G-829114`, matching the NodeODX deployment; the Tapis URI uses the corresponding
`/corral-repl/utexas/BCS26030/NodeODX` replica path. The Tapis job itself only executes the SIF;
it never runs apt, sudo, a compiler, or a network download.

Required acceptance metadata:

```text
OpenSplat source commit
base image digest
Ubuntu version
compiler/CMake versions
OpenCV version
LibTorch version and archive SHA256
CUDA toolkit version and image digest (CUDA profile)
CMAKE_CUDA_ARCHITECTURES (CUDA profile)
final SIF SHA256
```

The GitHub Actions build is intentionally separate from LS6. Do not register or upload the SIF
or Tapis ZIP until the hashes and fixture results have been reviewed.
