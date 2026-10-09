#!/usr/bin/env python3
"""Copy an ODX/OpenSfM project into a self-contained job directory."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"project staging failed: {message}")


def below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_image_entry(entry: str, project: Path, sfm_root: Path, container_project: Path) -> Path:
    raw = Path(entry)
    candidates: list[Path] = []
    if raw.is_absolute():
        try:
            candidates.append(project / raw.relative_to(container_project))
        except ValueError:
            pass
        candidates.append(project / "images" / raw.name)
    else:
        candidates.extend((sfm_root / raw, project / raw))

    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved.is_file() and below(resolved, project):
            return resolved
    fail(f"image_list.txt entry cannot be resolved inside staged project: {entry}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--container-project", required=True, type=Path)
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    if not source.is_dir():
        fail(f"source is not a directory: {source}")
    destination = args.destination
    if destination.exists():
        fail(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    # symlinks=False copies the target contents rather than preserving links to
    # Tapis/NodeODM work directories that will not exist inside Apptainer.
    shutil.copytree(source, destination, symlinks=False)
    destination = destination.resolve()
    links = [path for path in destination.rglob("*") if path.is_symlink()]
    if links:
        fail(f"staged project still contains symlink: {links[0]}")

    sfm_root = destination / "opensfm" if (destination / "opensfm").is_dir() else destination
    image_list = sfm_root / "image_list.txt"
    if not image_list.is_file():
        fail(f"missing {image_list}")

    entries = [line.strip() for line in image_list.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not entries:
        fail("image_list.txt is empty")

    total_bytes = 0
    for entry in entries:
        image = resolve_image_entry(entry, destination, sfm_root, args.container_project)
        total_bytes += image.stat().st_size

    print(json.dumps({
        "source_project": str(source),
        "staged_project": str(destination.resolve()),
        "sfm_root": str(sfm_root.resolve()),
        "container_project": str(args.container_project),
        "image_count": len(entries),
        "image_bytes": total_bytes,
        "symlinks_preserved": False,
        "image_list_rewritten": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
