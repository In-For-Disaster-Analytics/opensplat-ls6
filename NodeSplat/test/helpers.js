'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {load} = require('../config');

const RUN = '11111111-1111-4111-8111-111111111111';
const TASK = '22222222-2222-4222-8222-222222222222';
const SOURCE = '33333333-3333-4333-8333-333333333333';
const JOB = '44444444-4444-4444-8444-444444444444';
const API = 'a'.repeat(43);
const SECRET = 'registration-secret-0123456789';

// A fake launcher is a bash script: tests control stdout, exit status and artifacts.
function fixture(launcherBody, overrides = {}) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'nodesplat-'));
    const dirs = {input: path.join(root, 'input'), output: path.join(root, 'output'), work: path.join(root, 'work')};
    for (const dir of Object.values(dirs)) fs.mkdirSync(dir, {mode: 0o700});
    const input = path.join(dirs.input, RUN, 'input');
    fs.mkdirSync(path.join(input, 'images'), {recursive: true});
    const assets = {cameras_path: 'cameras.json', shots_path: 'shots.geojson', point_cloud_path: 'cloud.laz'};
    for (const name of Object.values(assets)) fs.writeFileSync(path.join(input, name), 'x');
    fs.writeFileSync(path.join(input, 'images', 'a.jpg'), 'x');
    const manifest = {schema_version: 1, input_format: 'webodm-assets', task_id: SOURCE, image_size: 1920,
        images: [{filename: 'a.jpg', path: 'images/a.jpg'}], rtc_offset: [0, 0], ...assets};
    const manifestBytes = JSON.stringify(manifest);
    fs.writeFileSync(path.join(input, 'webodm-input.json'), manifestBytes);
    const launcher = path.join(root, 'launcher.sh');
    fs.writeFileSync(launcher, '#!/usr/bin/env bash\n' + launcherBody, {mode: 0o700});
    const env = {NODESPLAT_ENABLED: 'YES', NODESPLAT_RUN_ID: RUN, NODESPLAT_CLUSTER_TASK_ID: TASK,
        NODESPLAT_TAPIS_JOB_ID: JOB, NODESPLAT_PROFILE_ID: 'nodesplat-v1', NODESPLAT_APP_ID: 'nodesplat',
        NODESPLAT_APP_VERSION: '0.1.0', NODESPLAT_BIND_HOST: '127.0.0.1', NODESPLAT_PORT: '8080',
        NODESPLAT_REGISTRATION_SECRET: SECRET, NODESPLAT_API_CAPABILITY: API,
        NODESPLAT_INPUT_ROOT: dirs.input, NODESPLAT_OUTPUT_ROOT: dirs.output, NODESPLAT_WORK_ROOT: dirs.work,
        NODESPLAT_PUBLIC_URL: 'http://c301-001.ls6.example:8080', NODESPLAT_CALLBACK_URL: 'https://cluster.example/',
        NODESPLAT_LEASE_DEADLINE: String(Math.floor(Date.now() / 1000) + 3600),
        PATH: process.env.PATH, ...overrides};
    const config = load(env);
    config.launcher = launcher;
    return {root, config, dirs, input, manifest, body: {
        run_id: RUN, source_task_id: SOURCE, manifest_sha256: crypto.createHash('sha256').update(manifestBytes).digest('hex'),
        settings: {num_iterations: 100, image_size: 1920}, 'set-uuid': TASK}};
}

// Launcher that behaves like tapisjob_app.sh: logs, then writes the PLY and provenance.
const SUCCESS = `
echo "[opensplat-ls6] starting profile=cuda"
echo "Step 50/100 loss 0.1"
out="$_tapisJobWorkingDir/output"; mkdir -p "$out"
printf 'ply\\nformat binary_little_endian 1.0\\nend_header\\nDATA' > "$out/opensplat-$_tapisJobUUID.ply"
bytes=$(wc -c < "$out/opensplat-$_tapisJobUUID.ply" | tr -d ' ')
sha=$( (sha256sum "$out/opensplat-$_tapisJobUUID.ply" 2>/dev/null || shasum -a 256 "$out/opensplat-$_tapisJobUUID.ply") | cut -d' ' -f1)
cat > "$out/opensplat-$_tapisJobUUID.manifest.json" <<EOF
{"tapis_job_uuid":"$_tapisJobUUID","app":{"id":"$OPENSPLAT_APP_ID","version":"$OPENSPLAT_APP_VERSION"},
 "preparation":{"task_id":"${SOURCE}"},"num_iterations":100,"output":{"sha256":"$sha","bytes":$bytes}}
EOF
`;

async function until(predicate, timeout = 10000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
        if (await predicate()) return;
        await new Promise(resolve => setTimeout(resolve, 20));
    }
    throw new Error('Timed out waiting for condition');
}

module.exports = {fixture, until, SUCCESS, RUN, TASK, SOURCE, JOB, API, SECRET};
