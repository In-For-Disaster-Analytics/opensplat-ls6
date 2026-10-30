'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {load} = require('../config');
const {Task, STATUS} = require('../libs/Task');
const {createServer, coordinator} = require('../index');
const {fixture, until, SUCCESS, RUN, TASK, JOB, API, SECRET} = require('./helpers');

async function serve(f, task = new Task(f.config)) {
    const {server} = createServer(f.config, task);
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const base = `http://127.0.0.1:${server.address().port}`;
    const call = (route, {method = 'GET', body, token = API} = {}) => fetch(base + route, {method,
        headers: {...(token ? {Authorization: 'Bearer ' + token} : {}), 'Content-Type': 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body)});
    return {call, task, close: () => { server.closeAllConnections(); server.close(); }};
}

test('configuration fails closed and validates credentials and the advertised address', () => {
    const f = fixture('exit 0');
    assert.throws(() => load({...f.config.env, NODESPLAT_ENABLED: 'NO'}), /disabled/);
    // The per-job API token is the only credential; a cluster-wide secret is neither required nor read.
    assert.equal('registrationSecret' in load({...f.config.env, NODESPLAT_REGISTRATION_SECRET: SECRET}), false);
    assert.throws(() => load({...f.config.env, NODESPLAT_PUBLIC_URL: 'http://node.example:8080/path'}), /service URL/);
    // The retired per-job callback capability is no longer required or read
    const {NODESPLAT_CALLBACK_CAPABILITY, ...rest} = f.config.env;
    assert.ok(load(rest));
    const config = load(f.config.env);
    assert.equal(config.advertisedHost, 'c301-001.ls6.example');
    assert.equal(config.advertisedPort, 8080);
    assert.equal(load({...f.config.env, NODESPLAT_PUBLIC_URL: 'https://node.example'}).advertisedPort, 443);
    assert.throws(() => load({...f.config.env, NODESPLAT_API_CAPABILITY: 'short'}), /capability/);
    assert.throws(() => load({...f.config.env, NODESPLAT_INPUT_ROOT: 'relative'}), /absolute/);
    assert.throws(() => load({...f.config.env, NODESPLAT_PORT: undefined}), /Invalid NODESPLAT_PORT/);
    assert.throws(() => load({...f.config.env, NODESPLAT_CALLBACK_URL: 'https://u:p@cluster.example'}), /service URL/);
    assert.throws(() => load({...f.config.env, NODESPLAT_LEASE_DEADLINE: '1'}), /expired/);
});

test('API requires the worker capability and advertises the fixed profile', async () => {
    const f = fixture('exit 0');
    const s = await serve(f);
    try {
        assert.equal((await s.call('/info', {token: null})).status, 401);
        assert.equal((await s.call('/info', {token: 'wrong'})).status, 401);
        const info = await (await s.call('/info')).json();
        assert.equal(info.engine, 'nodesplat');
        assert.deepEqual(info.capabilities, ['opensplat-webodm-v1']);
        assert.equal(info.maxConcurrency, 1);
        const options = await (await s.call('/options')).json();
        assert.deepEqual(options.map(o => o.name), ['num_iterations', 'image_size']);
    } finally { s.close(); }
});

test('expired lease rejects every request', async () => {
    const f = fixture('exit 0');
    f.config.leaseDeadline = Date.now() - 1;
    const s = await serve(f);
    try { assert.equal((await s.call('/info')).status, 401); } finally { s.close(); }
});

test('rejects invalid identity, settings and unknown fields', async () => {
    const f = fixture('exit 0');
    const s = await serve(f);
    try {
        for (const patch of [{run_id: '99999999-9999-4999-8999-999999999999'}, {'set-uuid': JOB},
            {settings: {num_iterations: 0, image_size: 1920}}, {settings: {num_iterations: 1001, image_size: 1920}},
            {settings: {num_iterations: 10, image_size: 5}}, {settings: {num_iterations: 10, image_size: 4097}},
            {settings: {num_iterations: 10, image_size: 1920, extra: 1}}, {manifest_sha256: 'zz'},
            {callback_url: 'http://evil.example'}, {command: 'rm -rf /'}]) {
            const response = await s.call('/task/new', {method: 'POST', body: {...f.body, ...patch}});
            assert.equal(response.status, 400, JSON.stringify(patch));
        }
        assert.equal(s.task.record, null);
    } finally { s.close(); }
});

test('rejects a changed input manifest before starting any process', async () => {
    const f = fixture('touch "$0.started"');
    fs.appendFileSync(path.join(f.input, 'webodm-input.json'), ' ');
    const s = await serve(f);
    try {
        const response = await s.call('/task/new', {method: 'POST', body: f.body});
        assert.equal(response.status, 400);
        assert.match((await response.json()).error, /checksum/);
        assert.equal(fs.existsSync(f.config.launcher + '.started'), false);
    } finally { s.close(); }
});

test('rejects symlinked input assets', async () => {
    const f = fixture('exit 0');
    const asset = path.join(f.input, 'cloud.laz');
    fs.rmSync(asset);
    fs.symlinkSync('/etc/hosts', asset);
    const s = await serve(f);
    try { assert.equal((await s.call('/task/new', {method: 'POST', body: f.body})).status, 400); } finally { s.close(); }
});

test('successful run publishes verified artifacts, console and progress', async () => {
    const f = fixture(SUCCESS);
    const s = await serve(f);
    try {
        const created = await s.call('/task/new', {method: 'POST', body: f.body});
        assert.equal(created.status, 200);
        assert.equal((await created.json()).uuid, TASK);
        // Identical replay is idempotent; changed inputs conflict.
        assert.equal((await s.call('/task/new', {method: 'POST', body: f.body})).status, 200);
        assert.equal((await s.call('/task/new', {method: 'POST', body: {...f.body,
            settings: {num_iterations: 50, image_size: 1920}}})).status, 409);
        await s.task.done;
        const info = await (await s.call(`/task/${TASK}/info`)).json();
        assert.equal(info.status.code, STATUS.COMPLETED);
        assert.equal(info.phase, 'result_ready');
        assert.equal(info.result_ready, true);
        assert.deepEqual(info.progress, {iteration: 50, total: 100});
        const manifest = await (await s.call(`/task/${TASK}/download/manifest.json`)).json();
        assert.equal(manifest.run_id, RUN);
        assert.equal(manifest.cluster_task_uuid, TASK);
        assert.equal(manifest.tapis_job_uuid, JOB);
        assert.equal(manifest.output.bytes, fs.statSync(path.join(f.dirs.output, RUN, 'model.ply')).size);
        const model = Buffer.from(await (await s.call(`/task/${TASK}/download/model.ply`)).arrayBuffer());
        assert.equal(model.subarray(0, 4).toString(), 'ply\n');
        const lines = await (await s.call(`/task/${TASK}/output?line=0`)).json();
        assert.ok(lines.some(line => /starting profile/.test(line)));
        assert.deepEqual(await (await s.call(`/task/${TASK}/output?line=${lines.length}`)).json(), []);
        assert.equal(fs.statSync(path.join(f.dirs.output, RUN, 'model.ply')).mode & 0o077, 0);
    } finally { s.close(); }
});

test('failed process never publishes artifacts and download is allowlisted', async () => {
    const f = fixture('echo "boom Authorization: Bearer abc.def secret=hunter2"; exit 3');
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await s.task.done;
        const info = await (await s.call(`/task/${TASK}/info`)).json();
        assert.equal(info.status.code, STATUS.FAILED);
        assert.equal(info.result_ready, false);
        assert.equal(fs.existsSync(path.join(f.dirs.output, RUN, 'model.ply')), false);
        assert.equal((await s.call(`/task/${TASK}/download/model.ply`)).status, 404);
        for (const asset of ['..%2fworker-state.json', 'worker-state.json', '%2fetc%2fpasswd', 'console.txt%00']) {
            assert.equal((await s.call(`/task/${TASK}/download/${asset}`)).status, 404, asset);
        }
        const text = await (await s.call(`/task/${TASK}/download/console.txt`)).text();
        assert.match(text, /boom/);
        assert.doesNotMatch(text, /hunter2|abc\.def/);
    } finally { s.close(); }
});

test('provenance mismatch is rejected even when the process exits zero', async () => {
    const f = fixture(SUCCESS.replace('"num_iterations":100', '"num_iterations":7'));
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await s.task.done;
        assert.equal(s.task.info().status.code, STATUS.FAILED);
        assert.equal(fs.existsSync(path.join(f.dirs.output, RUN, 'model.ply')), false);
    } finally { s.close(); }
});

test('child never inherits credentials or the user token', async () => {
    const f = fixture('env | grep -E "NODESPLAT_|JWT|TAPIS_TOKEN|GRANT" | sed "s/=.*//" || echo none; exit 1');
    f.config.env.TAPIS_TOKEN = 'eyJhbGciOiJ.eyJzdWIiOiJ.c2ln';
    f.config.env.NODESPLAT_GRANT_SECRET = 'g'.repeat(40);
    f.config.env.NODESPLAT_REGISTRATION_SECRET = SECRET;
    const childEnv = require('../libs/opensplatRunner').environment(f.config, 'in', 'work');
    assert.equal(Object.keys(childEnv).some(key => /CAPABILITY|GRANT|TOKEN|JWT|SECRET/.test(key)), false);
    assert.equal(Object.values(childEnv).some(value => /eyJ|g{40}/.test(value) || value.includes(SECRET) || value.includes(API)), false);
    assert.equal('NODESPLAT_REGISTRATION_SECRET' in childEnv, false);
    assert.equal(childEnv.OPENSPLAT_STREAM_LOG, '1');
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await s.task.done;
        const text = fs.readFileSync(path.join(f.dirs.output, RUN, 'console.txt'), 'utf8');
        assert.doesNotMatch(text, /NODESPLAT_(API_CAPABILITY|REGISTRATION_SECRET)|GRANT|TAPIS_TOKEN/);
    } finally { s.close(); }
});

test('cancel terminates the whole process group and reports canceled', async () => {
    const f = fixture('sleep 300 & echo $! > "$0.child"; wait');
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await until(() => fs.existsSync(f.config.launcher + '.child') && s.task.child);
        const grandchild = Number(fs.readFileSync(f.config.launcher + '.child', 'utf8'));
        const response = await s.call('/task/cancel', {method: 'POST', body: {uuid: TASK}});
        assert.equal(response.status, 200);
        await s.task.done;
        assert.equal(s.task.info().status.code, STATUS.CANCELED);
        await until(() => { try { process.kill(grandchild, 0); return false; } catch (e) { return e.code === 'ESRCH'; } });
        // Idempotent after termination; remove only after a terminal state.
        assert.equal((await s.call('/task/cancel', {method: 'POST', body: {uuid: TASK}})).status, 200);
        assert.equal((await s.call('/task/cancel', {method: 'POST', body: {uuid: JOB}})).status, 404);
        assert.equal((await s.call('/task/remove', {method: 'POST', body: {uuid: TASK}})).status, 200);
        assert.equal(fs.existsSync(path.join(f.dirs.output, RUN, 'console.txt')), true);
    } finally { s.close(); }
});

test('remove is refused while the task is active', async () => {
    const f = fixture('sleep 300');
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await until(() => s.task.child);
        assert.equal((await s.call('/task/remove', {method: 'POST', body: {uuid: TASK}})).status, 409);
        s.task.cancel();
        await s.task.done;
    } finally { s.close(); }
});

test('console capture is capped, truncation is reported and training continues', async () => {
    const f = fixture('for i in $(seq 1 200); do echo "line $i padding padding padding padding"; done; exit 1');
    f.config.maxLogBytes = 1024;
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await s.task.done;
        const size = fs.statSync(path.join(f.dirs.output, RUN, 'console.txt')).size;
        assert.ok(size <= 1024, `console grew to ${size}`);
        const lines = s.task.output(0);
        assert.equal(lines.filter(line => /capture limit reached/.test(line)).length, 1);
        assert.equal(s.task.info().truncated, true);
    } finally { s.close(); }
});

test('output pages are bounded and cursors validated', async () => {
    const f = fixture('for i in $(seq 1 1200); do echo "line $i"; done; exit 1');
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await s.task.done;
        const first = await (await s.call(`/task/${TASK}/output?line=0`)).json();
        assert.equal(first.length, 500);
        const second = await (await s.call(`/task/${TASK}/output?line=500`)).json();
        assert.equal(second.length, 500);
        assert.notDeepEqual(first[0], second[0]);
        for (const bad of ['-1', 'abc', '1e3', '99999999999999999']) {
            assert.equal((await s.call(`/task/${TASK}/output?line=${bad}`)).status, 400, bad);
        }
        assert.equal((await s.call(`/task/${JOB}/output?line=0`)).status, 404);
    } finally { s.close(); }
});

test('restart with a stale running record fails the attempt without retraining', async () => {
    const f = fixture('sleep 300');
    const first = new Task(f.config);
    await first.create(f.body);
    await until(() => first.child);
    first.cancelRequested = false;
    const pid = first.child.pid;
    // Simulate worker death: a fresh Task sees a non-terminal record.
    const record = JSON.parse(fs.readFileSync(path.join(f.dirs.output, RUN, 'worker-state.json'), 'utf8'));
    assert.equal(record.status.code, STATUS.RUNNING);
    const second = new Task(f.config, {startProcess: () => { throw new Error('must not restart'); }});
    assert.equal(second.info().status.code, STATUS.FAILED);
    assert.match(second.info().error, /restarted/);
    assert.equal(await second.create(f.body).then(() => 'ok', e => e.status), 'ok');
    process.kill(-pid, 'SIGKILL');
    await first.done;
});

test('stored allocation identity must match configuration', () => {
    const f = fixture(SUCCESS);
    const record = path.join(f.dirs.output, RUN);
    fs.mkdirSync(record, {recursive: true});
    fs.writeFileSync(path.join(record, 'worker-state.json'), JSON.stringify({uuid: TASK, run_id: RUN,
        tapis_job_uuid: 'another-job', profile_id: 'nodesplat-v1', status: {code: STATUS.COMPLETED}}));
    assert.throws(() => new Task(f.config), /identity mismatch/);
});

test('API capability is redacted from console output', async () => {
    const f = fixture(`echo "token ${API}"; exit 1`);
    const s = await serve(f);
    try {
        await s.call('/task/new', {method: 'POST', body: f.body});
        await s.task.done;
        const text = fs.readFileSync(path.join(f.dirs.output, RUN, 'console.txt'), 'utf8');
        assert.match(text, /token \[REDACTED\]/);
        assert.equal(text.includes(API), false);
    } finally { s.close(); }
});

function recorder(behavior = () => ({ok: true})) {
    const calls = [];
    const fetch = async (url, options) => {
        calls.push({url, options, body: JSON.parse(options.body)});
        const result = behavior(calls.length);
        if (result instanceof Error) throw result;
        return result;
    };
    return {calls, fetch};
}

test('coordinator posts the NodeODX-style registration webhook on every tick', async () => {
    const f = fixture(SUCCESS);
    const task = new Task(f.config);
    const r = recorder();
    const c = coordinator(f.config, task, {fetch: r.fetch});
    await c.tick(); await c.tick(); await c.tick();
    assert.equal(r.calls.length, 3);
    for (const call of r.calls) {
        assert.equal(call.url, 'https://cluster.example/webhook/register-node');
        assert.equal(call.options.method, 'POST');
        assert.equal(call.options.redirect, 'error');
        assert.deepEqual(call.options.headers, {'Content-Type': 'application/json'});
        assert.equal(call.options.headers.Authorization, undefined);
        assert.deepEqual(call.body, {hostname: 'c301-001.ls6.example', port: 8080, token: API,
            tapisJobUuid: JOB, registrationUuid: TASK, role: 'nodesplat', nodeReady: true});
        assert.ok(call.options.signal instanceof AbortSignal);
    }
    assert.equal(c.stopped, false);
});

test('coordinator retries registration after a failure or non-2xx response', async () => {
    const f = fixture(SUCCESS);
    const task = new Task(f.config);
    const r = recorder(n => n === 1 ? new Error('down') : n === 2 ? {ok: false, status: 503} : {ok: true});
    const c = coordinator(f.config, task, {fetch: r.fetch});
    await c.tick(); await c.tick(); await c.tick();
    assert.equal(r.calls.length, 3);
    assert.equal(c.stopped, false);
});

test('coordinator keeps registering through completion and stops once ClusterODX removes the task', async () => {
    const f = fixture(SUCCESS);
    const task = new Task(f.config);
    const r = recorder();
    const c = coordinator(f.config, task, {fetch: r.fetch});
    await task.create(f.body);
    await task.done;
    assert.equal(task.info().status.code, STATUS.COMPLETED);
    await c.tick();
    assert.equal(c.stopped, false);
    // Handoff happens through the NodeODX-style removal call, not a heartbeat acknowledgment
    const s = await serve(f, task);
    try { assert.equal((await s.call('/task/remove', {method: 'POST', body: {uuid: TASK}})).status, 200); } finally { s.close(); }
    const before = r.calls.length;
    await c.tick();
    assert.equal(r.calls.length, before + 1, 'still registers on the tick that observes removal');
    assert.equal(c.stopped, true);
    await c.tick();
    assert.equal(r.calls.length, before + 1, 'no further requests once stopped');
});

test('coordinator stops after the grace period when the task is never removed', async () => {
    const f = fixture('exit 1');
    f.config.handoffMs = 50;
    const task = new Task(f.config);
    const r = recorder(() => new Error('cluster unreachable'));
    const c = coordinator(f.config, task, {fetch: r.fetch});
    await task.create(f.body);
    await task.done;
    await c.tick();
    assert.equal(c.stopped, false);
    await new Promise(resolve => setTimeout(resolve, 80));
    await c.tick();
    assert.equal(c.stopped, true);
});

test('coordinator cancels the child and stops when the lease expires', async () => {
    const f = fixture('sleep 300');
    const task = new Task(f.config);
    await task.create(f.body);
    await until(() => task.child);
    f.config.leaseDeadline = Date.now() - 1;
    const r = recorder();
    const c = coordinator(f.config, task, {fetch: r.fetch});
    await c.tick();
    assert.equal(c.stopped, true);
    assert.equal(r.calls.length, 0, 'an expired lease does not register again');
    await task.done;
    assert.equal(task.info().status.code, STATUS.CANCELED);
});
