"""Validate and selectively stage operator-owned WebODM input snapshots."""
import hashlib
import json
import math
import os
import stat
from pathlib import Path

MANIFEST = 'webodm-input.json'
MAX_MANIFEST = 8 * 1024 * 1024


def load_input(project, max_images=20000, max_bytes=1099511627776):
    project = Path(project).resolve(strict=True)
    manifest = project / MANIFEST
    if manifest.is_symlink() or manifest.stat().st_size > MAX_MANIFEST:
        raise ValueError('invalid or oversized manifest')
    if any((project / p).exists() for p in ('reconstruction.json', 'opensfm/reconstruction.json')):
        raise ValueError('ambiguous WebODM and OpenSfM input')
    data = json.loads(manifest.read_text())
    if data.get('schema_version') != 1 or data.get('input_format') != 'webodm-assets':
        raise ValueError('unsupported WebODM manifest schema')
    if not isinstance(data.get('task_id'), str) or not data['task_id']:
        raise ValueError('task_id is required')
    offset = data.get('rtc_offset')
    if not isinstance(offset, list) or len(offset) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in offset):
        raise ValueError('rtc_offset must contain two finite numbers')
    size = data.get('image_size')
    if type(size) is not int or not 0 <= size <= 32768:
        raise ValueError('invalid image_size')
    images = data.get('images')
    if not isinstance(images, list) or not 1 <= len(images) <= max_images:
        raise ValueError('invalid image count')
    names = set()
    paths = [data.get(k) for k in ('cameras_path', 'shots_path', 'point_cloud_path')]
    for image in images:
        name = image.get('filename') if isinstance(image, dict) else None
        if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name or '\0' in name or name in names:
            raise ValueError('invalid or duplicate image filename')
        if Path(name).suffix.lower() not in ('.jpg', '.jpeg'):
            raise ValueError('only JPEG images are supported')
        names.add(name)
        paths.append(image.get('path'))
    files = []
    seen = set()
    total = manifest.stat().st_size
    for item in paths:
        if not isinstance(item, str) or not item or '\\' in item or '\0' in item:
            raise ValueError('invalid input path')
        relative = Path(item)
        if relative.is_absolute() or '..' in relative.parts or item == MANIFEST or relative in seen:
            raise ValueError('invalid or duplicate input path')
        seen.add(relative)
        target = (project / relative).resolve(strict=True)
        if not target.is_relative_to(project) or not stat.S_ISREG(target.stat().st_mode):
            raise ValueError('input path escapes project or is not regular')
        length = target.stat().st_size
        if length <= 0:
            raise ValueError('empty input asset')
        if item in (data['cameras_path'], data['shots_path']) and length > 64 * 1024 * 1024:
            raise ValueError('oversized camera metadata')
        total += length
        if total > max_bytes:
            raise ValueError('input byte limit exceeded')
        files.append((relative, target))
    # Reject file/directory collisions before creating staging directories.
    all_paths = seen | {Path(MANIFEST)}
    if any(parent in all_paths for p in all_paths for parent in p.parents if parent != Path('.')):
        raise ValueError('input path collision')
    return data, files, total


def stage_input(source, destination, max_images=20000, max_bytes=1099511627776):
    data, files, total = load_input(source, max_images, max_bytes)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    snapshots = []
    copied_bytes = 0
    for relative, target in [(Path(MANIFEST), Path(source) / MANIFEST)] + files:
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with open(target, 'rb') as src, open(output, 'xb') as dst:
            before = os.fstat(src.fileno())
            count = 0
            while True:
                block = src.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                copied_bytes += len(block)
                if copied_bytes > max_bytes or copied_bytes > total:
                    raise ValueError("input changed or byte limit exceeded during staging")
                if count > before.st_size:
                    raise ValueError('source changed during staging')
                digest.update(block)
                dst.write(block)
            after = os.fstat(src.fileno())
        current = target.stat()
        if count != before.st_size or any((s.st_size, s.st_mtime_ns, s.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino) for s in (after, current)):
            raise ValueError('source changed during staging')
        snapshots.append({'path': str(relative), 'bytes': count, 'mtime_ns': before.st_mtime_ns, 'sha256': digest.hexdigest()})
    if copied_bytes != total:
        raise ValueError("input size changed during staging")
    staged, _, _ = load_input(destination, max_images, max_bytes)
    if staged != data:
        raise ValueError('manifest changed during staging')
    return {'input_format': 'webodm-assets', 'task_id': data['task_id'], 'input_bytes': total, 'files': snapshots}
