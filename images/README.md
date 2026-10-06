# OpenSplat SIF build inputs

The Tapis ZIP deliberately does not contain a large compiler/runtime image. Build two separate
Linux artifacts from the pins in `opensplat-pins.env`:

- CPU profile: `GPU_RUNTIME=CPU` with CPU LibTorch;
- CUDA profile: CUDA 12.1.1, LibTorch 2.2.1, and an LS6 A100-compatible `CMAKE_CUDA_ARCHITECTURES=80`.

The upstream OpenSplat CMake configuration selects the GPU runtime at build time, so one SIF
must not be reused as both CPU and CUDA acceptance evidence. The upstream CUDA Dockerfile is a
useful reference for dependency installation and CMake flags, but the final SIF checksum and
build metadata must be recorded after the build.

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

Build/pull commands are intentionally not run from this repository. They require an approved
Linux/LS6 build environment and external artifact access. Do not register or upload the SIF or
Tapis ZIP until the hashes and fixture results have been reviewed.
