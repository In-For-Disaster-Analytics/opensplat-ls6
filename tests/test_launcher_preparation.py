import hashlib
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_webodm_input

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("timeout"), "GNU timeout required by Linux launcher")
    def test_preparation_failure_prevents_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            test_webodm_input.InputTests().fixture(source)
            tools = root / 'bin'
            tools.mkdir()
            fake = tools / 'apptainer'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\nexit 23\n')
            fake.chmod(0o755)
            sif = root / 'runtime.sif'
            sif.write_bytes(b'fake-image')
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                       CALL_LOG=str(root / 'calls'), OPENSPLAT_SIF_PATH=str(sif),
                       OPENSPLAT_PREPARE_SIF=str(sif), OPENSPLAT_PREPARE_SHA256=hashlib.sha256(sif.read_bytes()).hexdigest(),
                       OPENSPLAT_IMPORT_PATH_ROOTS=str(root), _tapisJobWorkingDir=str(root / 'job'),
                       _tapisExecSystemOutputDir=str(root / 'output'))
            result = subprocess.run(['bash', str(ROOT / 'tapisjob_app.sh'), str(source), '10'], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = (root / 'calls').read_text()
            self.assertIn('/app/prepare_webodm.py', calls)
            self.assertNotIn('/opt/opensplat/bin/opensplat', calls)
            self.assertFalse(list((root / 'output').glob('*.ply')))
