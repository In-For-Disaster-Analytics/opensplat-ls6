import ast
import importlib.util
import json
from pathlib import Path
import struct
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import prepare_webodm as preparation
import webodm_export as exporter


class ConversionTests(unittest.TestCase):
    def fixture(self, root):
        root.mkdir()
        Image.new('RGB', (20, 10), (12, 24, 36)).save(root / 'a.jpg')
        (root / 'cameras.json').write_text(json.dumps({'cam': {'width': 20, 'height': 10, 'focal': .7}}))
        (root / 'shots.geojson').write_text(json.dumps({'features': [{'properties': {
            'filename': 'a.jpg', 'camera': 'v2 cam', 'rotation': [.2, -.1, .3], 'translation': [101, 202, 3]}}]}))
        (root / 'cloud.laz').write_bytes(b'placeholder')
        manifest = {'schema_version': 1, 'input_format': 'webodm-assets', 'task_id': 'test',
                    'cameras_path': 'cameras.json', 'shots_path': 'shots.geojson',
                    'point_cloud_path': 'cloud.laz', 'rtc_offset': [100, 200], 'image_size': 10,
                    'images': [{'filename': 'a.jpg', 'path': 'a.jpg'}]}
        (root / 'webodm-input.json').write_text(json.dumps(manifest))
        return manifest

    def test_binary_pose_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            self.fixture(root)
            task = preparation.ManifestTask(root)
            cameras, shots, _, _ = exporter.load_scene(task, 10)
            self.assertEqual(shots[0]['center'], [1., 2., 3.])
            binary = exporter.write_cameras_bin(cameras)
            self.assertEqual(struct.unpack_from('<iiQQ', binary, 8), (1, 3, 10, 5))
            np.testing.assert_allclose(struct.unpack_from('<5d', binary, 32), [7, 5, 2.5, 0, 0], atol=1e-9)
            image = exporter.write_images_bin(shots)
            q = np.array(struct.unpack_from('<4d', image, 12))
            theta = np.linalg.norm([.2, -.1, .3])
            np.testing.assert_allclose(q, [np.cos(theta/2), * (np.array([.2,-.1,.3])/theta*np.sin(theta/2))], atol=1e-9)

    def test_strict_scene_inputs(self):
        for change in ('unknown-camera', 'nonfinite', 'missing-image', 'escape', 'unsupported-camera', 'duplicate'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'source'
                m = self.fixture(root)
                if change == 'unknown-camera':
                    p = json.loads((root/'shots.geojson').read_text()); p['features'][0]['properties']['camera']='missing'; (root/'shots.geojson').write_text(json.dumps(p))
                elif change == 'nonfinite': m['rtc_offset'] = [float('nan'), 0]
                elif change == 'missing-image': (root/'a.jpg').unlink()
                elif change == 'escape': m['images'][0]['path']='../outside.jpg'; (root.parent/'outside.jpg').write_bytes(b'x')
                elif change == 'duplicate': m['images'].append(m['images'][0])
                else: (root/'cameras.json').write_text(json.dumps({'cam': {'width':20,'height':10,'focal':.7,'projection_type':'spherical'}}))
                (root/'webodm-input.json').write_text(json.dumps(m))
                with self.assertRaises((ValueError, FileNotFoundError)):
                    preparation.ManifestTask(root)

    @unittest.skipUnless(shutil.which('pdal'), 'PDAL is required for runtime integration test')
    def test_preparation_real_pdal_and_colmap_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'source'; self.fixture(root)
            # PDAL reads a tiny ASCII PLY as the colored source cloud.
            cloud = root/'cloud.ply'
            cloud.write_text('ply\nformat ascii 1.0\nelement vertex 1\nproperty double x\nproperty double y\nproperty double z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n101 202 3 12 24 36\n')
            m=json.loads((root/'webodm-input.json').read_text());m['point_cloud_path']='cloud.ply'; (root/'webodm-input.json').write_text(json.dumps(m))
            out=Path(tmp)/'out'; report=preparation.prepare(root,out)
            self.assertEqual(report['sparse_point_count'],1)
            with Image.open(out/'images/a.jpg') as im: self.assertEqual(im.size,(10,5))
            points=(out/'sparse/0/points3D.bin').read_bytes()
            np.testing.assert_allclose(struct.unpack_from('<3d',points,16),[1,2,3],atol=1e-6)
            self.assertEqual(struct.unpack_from('<3B',points,40),(12,24,36))
            self.assertTrue((out/'sparse/0/cameras.bin').is_file())
            self.assertTrue((out/'sparse/0/images.bin').is_file())

    @unittest.skipUnless(shutil.which('pdal'), 'PDAL is required for runtime integration test')
    def test_empty_cloud_aborts_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'source'; self.fixture(root)
            cloud = root/'cloud.ply'
            cloud.write_text('ply\nformat ascii 1.0\nelement vertex 0\nproperty double x\nproperty double y\nproperty double z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n')
            m=json.loads((root/'webodm-input.json').read_text());m['point_cloud_path']='cloud.ply'; (root/'webodm-input.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError):
                preparation.prepare(root,Path(tmp)/'out')

    def test_resize_failure_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                exporter.resize_image(str(Path(tmp)/'missing.jpg'),str(Path(tmp)/'out.jpg'),{'out_width':2,'out_height':2})


if __name__ == '__main__':
    unittest.main()
