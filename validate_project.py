#!/usr/bin/env python3
"""Validate the OpenSfM/ODX project layout consumed by OpenSplat."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"project preflight failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument(
        "--container-project",
        type=Path,
        help="container path where the project is bound; maps absolute image-list paths to the project",
    )
    parser.add_argument("--max-images", required=True, type=int)
    parser.add_argument("--max-bytes", required=True, type=int)
    args = parser.parse_args()

    project = args.project.resolve(strict=True)
    # Keep this path lexical: /var may be a host symlink (for example on macOS),
    # while it is a real container path at runtime.
    container_project = Path(args.container_project) if args.container_project else None
    if not project.is_dir():
        fail("project is not a directory")

    sfm_root = project / "opensfm" if (project / "opensfm").is_dir() else project
    reconstruction = sfm_root / "reconstruction.json"
    image_list = sfm_root / "image_list.txt"
    if not reconstruction.is_file():
        fail(f"missing {reconstruction}")
    if not image_list.is_file():
        fail(f"missing {image_list}")

    try:
        data = json.loads(reconstruction.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {reconstruction}: {exc}")
    if not isinstance(data, list) or not data:
        fail("reconstruction.json must contain a non-empty reconstruction list")
    if len(data) != 1:
        fail("multiple reconstructions are not accepted; select one project explicitly")
    first = data[0]
    if not isinstance(first, dict):
        fail("the reconstruction entry must be an object")
    for key in ("cameras", "shots", "points"):
        value = first.get(key)
        if not isinstance(value, dict) or not value:
            fail(f"reconstruction has no non-empty {key}")

    entries = [line.strip() for line in image_list.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not entries:
        fail("image_list.txt is empty")
    if len(entries) > args.max_images:
        fail(f"image count {len(entries)} exceeds limit {args.max_images}")

    total_bytes = 0
    missing = []
    escaped = []
    for entry in entries:
        candidate = Path(entry)
        if candidate.is_absolute() and container_project and (
            candidate == container_project or container_project in candidate.parents
        ):
            resolved = (project / candidate.relative_to(container_project)).resolve()
        else:
            resolved = candidate.resolve() if candidate.is_absolute() else (sfm_root / candidate).resolve()
        try:
            resolved.relative_to(project)
        except ValueError:
            escaped.append(str(resolved))
            continue
        if not resolved.is_file():
            missing.append(str(resolved))
            continue
        total_bytes += resolved.stat().st_size
        if total_bytes > args.max_bytes:
            fail(f"referenced image data exceeds limit {args.max_bytes} bytes")
    if escaped:
        fail(f"image_list.txt references paths outside the project: {escaped[0]}")
    if missing:
        fail(f"image_list.txt references missing images: {missing[0]}")

    print(json.dumps({
        "project": str(project),
        "sfm_root": str(sfm_root),
        "reconstruction": str(reconstruction),
        "image_list": str(image_list),
        "reconstruction_count": len(data),
        "camera_count": len(first["cameras"]),
        "shot_count": len(first["shots"]),
        "sparse_point_count": len(first["points"]),
        "image_count": len(entries),
        "referenced_image_bytes": total_bytes,
        "input_format": "odx-opensfm",
        "path_policy": "canonical-project-contained",
        "container_project": str(container_project) if container_project else None,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
