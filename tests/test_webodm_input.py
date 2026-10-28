import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from webodm_input import load_input, stage_input


class InputTests(unittest.TestCase):
    def fixture(self, root):
        root.mkdir()
        for name in ('cameras.json', 'shots.json', 'cloud.laz', 'photo.jpg'):
            (root / name).write_bytes(b'asset')
        data = dict(schema_version=1, input_format='webodm-assets', task_id='task', rtc_offset=[100, 200], image_size=1920,
                    cameras_path='cameras.json', shots_path='shots.json', point_cloud_path='cloud.laz', images=[dict(filename='photo.jpg', path='photo.jpg')])
        (root / 'webodm-input.json').write_text(json.dumps(data))
        return data

    def test_selective_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            self.fixture(root)
            (root / 'unrelated').write_text('do not copy')
            report = stage_input(root, Path(tmp) / 'staged')
            self.assertEqual(len(report['files']), 5)
            self.assertFalse((Path(tmp) / 'staged/unrelated').exists())
            self.assertTrue(all(len(f['sha256']) == 64 for f in report['files']))

    def test_reject_invalid_inputs_before_copy(self):
        mutations = [lambda d: d.update(rtc_offset=[float('nan'), 0]),
                     lambda d: d.update(image_size=True),
                     lambda d: d.update(cameras_path='../outside'),
                     lambda d: d['images'].append(d['images'][0].copy()),
                     lambda d: d.update(shots_path='photo.jpg/child')]
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'source'
                data = self.fixture(root)
                mutate(data)
                (root / 'webodm-input.json').write_text(json.dumps(data))
                with self.assertRaises((ValueError, OSError)):
                    stage_input(root, Path(tmp) / 'staged')
                self.assertFalse((Path(tmp) / 'staged').exists())

    def test_escape_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            self.fixture(root)
            with self.assertRaises(ValueError):
                load_input(root, max_bytes=1)
            outside = Path(tmp) / 'outside'
            outside.write_bytes(b'outside')
            (root / 'photo.jpg').unlink()
            (root / 'photo.jpg').symlink_to(outside)
            with self.assertRaises(ValueError):
                load_input(root)

    def test_ambiguous_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            self.fixture(root)
            (root / 'reconstruction.json').write_text('[]')
            with self.assertRaises(ValueError):
                load_input(root)
