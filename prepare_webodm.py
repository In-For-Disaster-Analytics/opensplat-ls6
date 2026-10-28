#!/usr/bin/env python3
"""Prepare manifest-selected WebODM assets as a self-contained COLMAP project."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import time
import warnings

from PIL import Image
import webodm_export as exporter
from webodm_input import load_input

EXPORTER_REVISION = '51c8f98b35de920d347631bcb99ed06180a6cafd'


def contained(project, value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('Invalid input path')
    rel = Path(value)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Input paths must be project relative')
    path = (project / rel).resolve(strict=True)
    if not path.is_relative_to(project) or not path.is_file():
        raise ValueError('Input file escapes project or is not a file')
    return path


def finite_vector(value, length):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError('Invalid coordinate vector')
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Nonfinite coordinate vector')
    return result


class ManifestTask:
    def __init__(self, project):
        self.project = project.resolve(strict=True)
        manifest_file = self.project / 'webodm-input.json'
        if manifest_file.is_symlink():
            raise ValueError('Manifest cannot be a symlink')
        self.manifest, _, _ = load_input(self.project)
        m = self.manifest
        if m.get('schema_version') != 1 or m.get('input_format') != 'webodm-assets':
            raise ValueError('Unsupported WebODM manifest schema')
        self.rtc_offset = finite_vector(m.get('rtc_offset'), 2)
        self.image_size = m.get('image_size', 0)
        if type(self.image_size) is not int or not 0 <= self.image_size <= 65536:
            raise ValueError('Invalid image_size')
        self.ASSETS_MAP = {
            'cameras.json': str(contained(self.project, m['cameras_path'])),
            'shots.geojson': str(contained(self.project, m['shots_path'])),
            'georeferenced_model.laz': str(contained(self.project, m['point_cloud_path'])),
        }
        self.images = {}
        if not isinstance(m.get('images'), list) or not m['images']:
            raise ValueError('Manifest requires images')
        for item in m['images']:
            name = item['filename']
            if not isinstance(name, str) or not name or Path(name).name != name or '\x00' in name or '\\' in name:
                raise ValueError('Invalid image filename')
            if name in self.images:
                raise ValueError('Duplicate image filename')
            if Path(name).suffix.lower() not in ('.jpg', '.jpeg'):
                raise ValueError('Only JPEG images are supported')
            self.images[name] = contained(self.project, item['path'])
        self.validate_scene()

    def assets_path(self, path):
        return path

    def get_image_path(self, name):
        return str(self.images[name])

    def validate_scene(self):
        cameras = json.loads(Path(self.ASSETS_MAP['cameras.json']).read_text())
        if not isinstance(cameras, dict) or not cameras:
            raise ValueError('Missing cameras')
        normalized = {}
        for key, camera in cameras.items():
            name = exporter.normalize_camera_id(key)
            if name in normalized:
                raise ValueError('Duplicate camera id')
            for value in camera.values():
                if isinstance(value, (int, float)) and not math.isfinite(value):
                    raise ValueError('Nonfinite camera parameter')
            mapped = exporter.map_camera(camera, self.image_size)
            if min(mapped['width'], mapped['height']) <= 0 or not all(math.isfinite(v) for v in mapped['params']) or mapped['params'][0] <= 0:
                raise ValueError('Invalid camera calibration')
            normalized[name] = mapped
        geo = json.loads(Path(self.ASSETS_MAP['shots.geojson']).read_text())
        features = geo.get('features')
        if not isinstance(features, list) or not features:
            raise ValueError('Missing camera poses')
        seen = set()
        for feature in features:
            p = feature['properties']
            name = p.get('filename')
            if name not in self.images or name in seen:
                raise ValueError('Missing or duplicate shot image')
            seen.add(name)
            camera = normalized.get(exporter.normalize_camera_id(p.get('camera', '')))
            if camera is None:
                raise ValueError('Unknown shot camera')
            finite_vector(p.get('rotation'), 3)
            finite_vector(p.get('translation'), 3)
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(self.images[name]) as im:
                    if im.format != 'JPEG' or im.size != (camera['width'], camera['height']):
                        raise ValueError('Image dimensions/format do not match camera')
                    im.verify()
        if seen != set(self.images):
            raise ValueError('Manifest contains images without camera poses')


def prepare(project, output):
    started = time.monotonic()
    task = ManifestTask(project)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError('Refusing to overwrite preparation output')
    if output.resolve().is_relative_to(task.project):
        raise ValueError('Output cannot be inside input project')
    output.mkdir(parents=True, exist_ok=True)
    try:
        exporter.prepare_export(task, str(output), image_size=task.image_size)
        images = output / 'images'
        images.mkdir(exist_ok=True)
        for item in json.loads((output / 'images.json').read_text()):
            destination = images / item['name']
            if not destination.exists():
                shutil.copyfile(item['path'], destination)
        sparse = output / 'sparse' / '0'
        sparse.mkdir(parents=True)
        for filename in ('cameras.bin', 'images.bin', 'points3D.bin'):
            (output / filename).rename(sparse / filename)
        with (sparse / 'points3D.bin').open('rb') as stream:
            count = struct.unpack('<Q', stream.read(8))[0]
        (output / 'images.json').unlink()
        report = {'input_format': 'webodm-assets', 'task_id': task.manifest.get('task_id'),
                  'exporter_revision': EXPORTER_REVISION, 'rtc_offset': task.rtc_offset,
                  'image_size': task.image_size, 'image_count': len(task.images),
                  'sparse_point_count': count, 'duration_seconds': time.monotonic() - started,
                  'manifest_sha256': hashlib.sha256((task.project / 'webodm-input.json').read_bytes()).hexdigest()}
        return report
    except BaseException:
        # Partial products remain diagnostic only; caller must never train after failure.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.project, args.output), indent=2, sort_keys=True))
    except Exception as exc:
        parser.exit(1, f'WebODM preparation failed: {exc}\n')


if __name__ == '__main__':
    main()
