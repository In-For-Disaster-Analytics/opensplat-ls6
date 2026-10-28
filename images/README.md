# OpenSplat image and SIF build inputs

The Tapis ZIP deliberately does not contain a large compiler/runtime image. The repository's
GitHub Actions workflow builds and publishes two separate, self-contained OCI images from the
pins in `opensplat-pins.env`. The Tapis launcher pulls the selected tag into a SIF at job
startup, refreshing its Scratch cache by default:

- `ghcr.io/in-for-disaster-analytics/opensplat-ls6:cpu`: `GPU_RUNTIME=CPU` with CPU LibTorch;
- `ghcr.io/in-for-disaster-analytics/opensplat-ls6:cuda`: CUDA 12.1.1, LibTorch 2.2.1, and an
  LS6 A100-compatible `CMAKE_CUDA_ARCHITECTURES=80`.

The upstream OpenSplat CMake configuration selects the GPU runtime at build time, so one image
must not be reused as both CPU and CUDA acceptance evidence. The upstream CUDA Dockerfile is a
useful reference for dependency installation and CMake flags. The CI images are the runtime
contract for the Tapis app; the launcher converts the selected public OCI tag to a SIF on LS6,
records the SIF checksum, and stores it under `$SCRATCH/opensplat-ls6/sifs/`.

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

The direct LS6 smoke-test scripts still support manually staged SIFs under `$SCRATCH`, which is
useful when testing registry access or a specific digest. The Tapis job itself does not run apt,
sudo, or a compiler; it only performs the Apptainer OCI-to-SIF pull before executing OpenSplat.

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

### Candidate WebODM preparation runtime

`Dockerfile.prepare` isolates PDAL/Python preparation from CUDA/LibTorch training.
It does not start Django or require WebODM credentials. The current local WebODM image
was used only as a test harness (PDAL 2.3.0, NumPy 1.26.2, Pillow 11.3.0). The candidate
recipe requests PDAL 2.8, Python 3.11, NumPy 1.26.4, and Pillow 11.3.0; dependency solving,
Linux build, and LS6 acceptance must pass before deployment. Record the resulting
image digest and SIF SHA256; pass the latter to the launcher. No images are published
by local preparation tests.
