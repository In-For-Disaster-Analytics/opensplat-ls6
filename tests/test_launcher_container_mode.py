import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_webodm_input

ROOT = Path(__file__).resolve().parents[1]


def gnu_tools():
    # The launcher targets Linux (GNU timeout, realpath -e, sha256sum).
    try:
        return bool(shutil.which('timeout') and shutil.which('sha256sum') and
                    subprocess.run(['realpath', '-e', '/'], capture_output=True).returncode == 0)
    except OSError:
        return False


@unittest.skipUnless(gnu_tools(), 'GNU timeout/realpath/sha256sum required (Linux)')
class ContainerModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = self.tmp / 'source'
        test_webodm_input.InputTests().fixture(self.source)
        self.tools = self.tmp / 'bin'
        self.tools.mkdir()
        self.calls = self.tmp / 'calls'

    def tool(self, name, body):
        path = self.tools / name
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(0o755)
        return path

    def run_launcher(self, tools_only_path=False, **extra):
        env = dict(os.environ, CALL_LOG=str(self.calls), OPENSPLAT_IMPORT_PATH_ROOTS=str(self.tmp),
                   _tapisJobWorkingDir=str(self.tmp / 'job'), _tapisExecSystemOutputDir=str(self.tmp / 'output'),
                   LD_LIBRARY_PATH='/opt/libtorch-cuda/lib')
        env['PATH'] = str(self.tools) + os.pathsep + (os.environ['PATH'])
        env.update(extra)
        return subprocess.run(['bash', str(ROOT / 'tapisjob_app.sh'), str(self.source), '10'], env=env,
                              capture_output=True, text=True)

    def log(self):
        return self.calls.read_text() if self.calls.exists() else ''

    def test_preparation_runs_directly_on_real_paths_and_failure_stops_training(self):
        self.tool('apptainer', 'echo "APPTAINER $*" >> "$CALL_LOG"; exit 99\n')
        self.tool('python', 'echo "PREPARE ld=${LD_LIBRARY_PATH:-unset} $*" >> "$CALL_LOG"; exit 23\n')
        self.tool('opensplat', 'echo "TRAIN $*" >> "$CALL_LOG"; exit 0\n')
        result = self.run_launcher(OPENSPLAT_IN_CONTAINER='1', OPENSPLAT_BINARY=str(self.tools / 'opensplat'),
                                   NODESPLAT_IMAGE_REF='docker://ghcr.io/org/img:nodesplat',
                                   NODESPLAT_IMAGE_SHA256=hashlib.sha256(b'image').hexdigest())
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.log()
        self.assertIn('PREPARE', log)
        # Real staged/prepared paths, no /input and /prepared bind mounts
        self.assertIn(f'--project {self.tmp}/job/opensplat_workdir/runtime/data/', log)
        self.assertIn(f'--output {self.tmp}/job/opensplat_workdir/colmap-', log)
        self.assertNotIn('--project /input', log)
        # libtorch's library path is for OpenSplat only; preparation runs without it
        self.assertIn('PREPARE ld=unset', log)
        # Nested Apptainer is never started and training never begins after a failed preparation
        self.assertNotIn('APPTAINER', log)
        self.assertNotIn('TRAIN', log)
        self.assertNotIn('required command not found: apptainer', result.stderr)

    def test_batch_mode_is_unchanged_and_still_requires_apptainer(self):
        # Without the container switch the launcher keeps its original host-side behaviour
        isolated = self.tmp / 'isolated'
        isolated.mkdir()
        for name in ('bash', 'env', 'dirname', 'basename', 'realpath', 'python3', 'sha256sum', 'timeout', 'tr', 'awk', 'mkdir', 'cat'):
            found = shutil.which(name)
            if found:
                (isolated / name).symlink_to(found)
        result = self.run_launcher(PATH=str(isolated))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('required command not found: apptainer', result.stderr)

    def test_container_switch_must_be_zero_or_one(self):
        result = self.run_launcher(OPENSPLAT_IN_CONTAINER='yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OPENSPLAT_IN_CONTAINER must be 0 or 1', result.stderr)


if __name__ == '__main__':
    unittest.main()
