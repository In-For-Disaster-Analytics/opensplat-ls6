import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Records every call; `pull [--force] <dest> <source>` writes a fake image at <dest>.
FAKE_APPTAINER = r'''#!/bin/bash
echo "$*" >> "$CALL_LOG"
if [[ "$1" == "pull" ]]; then
  shift; while [[ "$1" == --* ]]; do shift; done
  printf 'fake-image' > "$1"
elif [[ "$1" == "exec" ]]; then
  env | grep '^APPTAINERENV_' | sed 's/=.*//' | sort >> "$ENV_LOG"
  env | grep -E '^APPTAINERENV_NODESPLAT_(IN_CONTAINER|IMAGE_REF|IMAGE_SHA256)=' | sort >> "$ENV_LOG"
fi
exit 0
'''


@unittest.skipUnless(shutil.which('sha256sum') and shutil.which('bash'), 'GNU coreutils required (Linux)')
class EntryScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tools = self.tmp / 'bin'
        self.tools.mkdir()
        self.write_tool('apptainer', FAKE_APPTAINER)
        self.job = self.tmp / 'job'
        self.inputs = self.tmp / 'in'
        self.outputs = self.tmp / 'out'
        for d in (self.job, self.inputs, self.outputs):
            d.mkdir()
        self.calls = self.tmp / 'calls'
        self.envlog = self.tmp / 'env'

    def write_tool(self, name, body):
        path = self.tools / name
        path.write_text(body)
        path.chmod(0o755)

    def run_entry(self, **extra):
        env = {'PATH': str(self.tools) + os.pathsep + os.environ['PATH'], 'CALL_LOG': str(self.calls),
               'ENV_LOG': str(self.envlog), '_tapisJobUUID': '44444444-4444-4444-8444-444444444444',
               '_tapisJobWorkingDir': str(self.job), 'NODESPLAT_PORT': '3101',
               'NODESPLAT_PUBLIC_URL': 'http://node.example:3101/', 'NODESPLAT_INPUT_ROOT': str(self.inputs),
               'NODESPLAT_OUTPUT_ROOT': str(self.outputs), 'NODESPLAT_API_CAPABILITY': 'a' * 43,
               'NODESPLAT_SIF_CACHE_DIR': str(self.tmp / 'sifs'), 'HOME': str(self.tmp),
               # Must never reach the container:
               'TAPIS_ACCESS_TOKEN': 'eyJsecret.token.value', 'AWS_SECRET_ACCESS_KEY': 'hunter2'}
        env.update(extra)
        return subprocess.run(['bash', str(ROOT / 'nodesplat_entry.sh')], env=env, capture_output=True, text=True)

    def calls_text(self):
        return self.calls.read_text() if self.calls.exists() else ''

    def test_container_mode_pulls_once_then_runs_the_worker_in_the_image(self):
        result = self.run_entry()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = self.calls_text().splitlines()
        self.assertEqual([l.split()[0] for l in lines], ['pull', 'exec'])
        self.assertIn('docker://ghcr.io/in-for-disaster-analytics/opensplat-ls6:nodesplat', lines[0])
        execute = lines[1]
        for expected in ('--nv', '--cleanenv', '--containall', '--no-home',
                         f'--bind {self.job}:{self.job}:rw', f'--bind {self.inputs}:{self.inputs}:ro',
                         f'--bind {self.outputs}:{self.outputs}:rw', '/opt/node/bin/node /opt/nodesplat/NodeSplat/index.js'):
            self.assertIn(expected, execute)
        # A second job reuses the cached image instead of pulling several GB again
        self.calls.write_text('')
        self.assertEqual(self.run_entry().returncode, 0)
        self.assertEqual([l.split()[0] for l in self.calls_text().splitlines()], ['exec'])

    def test_only_the_intended_environment_crosses_into_the_container(self):
        self.assertEqual(self.run_entry().returncode, 0)
        env = self.envlog.read_text()
        for name in ('APPTAINERENV_NODESPLAT_API_CAPABILITY', 'APPTAINERENV_NODESPLAT_PORT',
                     'APPTAINERENV__tapisJobUUID', 'APPTAINERENV_NODESPLAT_TAPIS_JOB_ID'):
            self.assertIn(name, env)
        self.assertNotIn('TAPIS_ACCESS_TOKEN', env)
        self.assertNotIn('AWS_SECRET', env)
        self.assertIn('APPTAINERENV_NODESPLAT_IN_CONTAINER=1', env)
        self.assertIn('APPTAINERENV_NODESPLAT_IMAGE_REF=docker://ghcr.io/', env)
        sha = [l for l in env.splitlines() if l.startswith('APPTAINERENV_NODESPLAT_IMAGE_SHA256=')]
        self.assertEqual(len(sha), 1)
        self.assertRegex(sha[0].split('=', 1)[1], r'^[a-f0-9]{64}$')

    def test_refresh_repulls_a_moving_tag_but_never_a_digest_pin(self):
        self.assertEqual(self.run_entry().returncode, 0)
        self.calls.write_text('')
        self.assertEqual(self.run_entry(NODESPLAT_REFRESH_SIF='1').returncode, 0)
        self.assertEqual([l.split()[0] for l in self.calls_text().splitlines()], ['pull', 'exec'])
        pinned = 'docker://ghcr.io/org/img@sha256:' + 'b' * 64
        self.assertEqual(self.run_entry(NODESPLAT_IMAGE=pinned).returncode, 0)
        self.calls.write_text('')
        self.assertEqual(self.run_entry(NODESPLAT_IMAGE=pinned, NODESPLAT_REFRESH_SIF='1').returncode, 0)
        self.assertEqual([l.split()[0] for l in self.calls_text().splitlines()], ['exec'])

    def test_unsafe_image_references_and_modes_are_refused_before_apptainer_runs(self):
        for image in ('docker://x; rm -rf /', 'oras://ghcr.io/x', 'ghcr.io/x', 'docker://', 'docker://a b'):
            result = self.run_entry(NODESPLAT_IMAGE=image)
            self.assertNotEqual(result.returncode, 0, image)
        self.assertNotEqual(self.run_entry(NODESPLAT_RUN_MODE='bogus').returncode, 0)
        self.assertEqual(self.calls_text(), '')

    def test_failed_pull_is_a_failure_and_leaves_no_partial_image(self):
        self.write_tool('apptainer', '#!/bin/bash\n[[ "$1" == pull ]] && { printf partial > "${@: -2:1}"; exit 1; }\nexit 0\n')
        result = self.run_entry()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to pull', result.stderr)
        self.assertEqual(list((self.tmp / 'sifs').glob('*.sif')), [])

    def test_host_mode_uses_the_given_node_binary_and_never_apptainer(self):
        self.write_tool('fake-node', '#!/bin/bash\necho "node $*" > "$CALL_LOG"\n')
        result = self.run_entry(NODESPLAT_RUN_MODE='host', NODESPLAT_NODE_BIN=str(self.tools / 'fake-node'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(ROOT / 'NodeSplat' / 'index.js'), self.calls_text())
        self.assertNotIn('apptainer', self.calls_text())

    def test_host_mode_without_node_explains_both_remedies(self):
        result = self.run_entry(NODESPLAT_RUN_MODE='host', NODESPLAT_NODE_BIN='/nonexistent/node')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('NODESPLAT_NODE_BIN', result.stderr)
        self.assertIn('container', result.stderr)


if __name__ == '__main__':
    unittest.main()
