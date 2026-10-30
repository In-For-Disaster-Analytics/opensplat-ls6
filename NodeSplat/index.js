'use strict';
const http = require('node:http');
const fs = require('node:fs');
const crypto = require('node:crypto');
const {Task, STATUS} = require('./libs/Task');
const {load} = require('./config');
function authorized(value, capability) {
    if (typeof value !== 'string') return false;
    const expected = Buffer.from('Bearer ' + capability), actual = Buffer.from(value);
    return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
}
function json(response, status, data) {
    response.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
    response.end(JSON.stringify(data));
}
async function body(request) {
    let value = ''; let size = 0;
    for await (const chunk of request) {
        size += chunk.length;
        if (size > 65536) { const error = new Error('Request too large'); error.status = 413; throw error; }
        value += chunk;
    }
    try { return JSON.parse(value); } catch (_) { throw new Error('Invalid JSON request'); }
}
function createServer(config, task = new Task(config)) {
    const server = http.createServer(async (request, response) => {
        try {
            if (!authorized(request.headers.authorization, config.apiCapability) || Date.now() >= config.leaseDeadline) return json(response, 401, {error: 'Invalid or expired worker capability'});
            const url = new URL(request.url, 'http://worker.invalid');
            if (request.method === 'GET' && url.pathname === '/info') return json(response, 200, {
                engine: 'nodesplat', version: '0.1.0', api_version: 1, capabilities: ['opensplat-webodm-v1'], maxConcurrency: 1,
                run_id: config.runId, cluster_task_uuid: config.taskId, tapis_job_uuid: config.jobId, profile_id: config.profileId
            });
            if (request.method === 'GET' && url.pathname === '/options') return json(response, 200, [
                {name: 'num_iterations', type: 'int', value: 100, min: 1, max: 1000},
                {name: 'image_size', type: 'int', value: 1920, min: 0, max: 4096}
            ]);
            if (request.method === 'POST' && url.pathname === '/task/new') return json(response, 200, await task.create(await body(request)));
            if (request.method === 'POST' && ['/task/cancel', '/task/remove'].includes(url.pathname)) {
                const data = await body(request);
                if (data.uuid !== config.taskId || !task.record) return json(response, 404, {error: 'Unknown task'});
                if (url.pathname === '/task/remove') {
                    if (![STATUS.COMPLETED, STATUS.FAILED, STATUS.CANCELED].includes(task.record.status.code)) return json(response, 409, {error: 'Task is active'});
                    // Retention is operator-managed. Logical removal never deletes an archive.
                    task.update({removed: true});
                    return json(response, 200, {success: true});
                }
                return json(response, 200, task.cancel());
            }
            const match = url.pathname.match(/^\/task\/([^/]+)\/(info|output|download\/([^/]+))$/);
            if (!match || match[1] !== config.taskId || !task.record) return json(response, 404, {error: 'Unknown task'});
            if (request.method !== 'GET') return json(response, 405, {error: 'Method not allowed'});
            if (match[2] === 'info') return json(response, 200, task.info());
            if (match[2] === 'output') {
                const raw = url.searchParams.get('line') || '0';
                if (!/^\d{1,12}$/.test(raw)) throw new Error('Invalid console line offset');
                return json(response, 200, task.output(Number(raw)));
            }
            const asset = task.download(match[3]);
            if (!asset) return json(response, 404, {error: 'Unknown artifact'});
            const fd = fs.openSync(asset, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
            response.writeHead(200, {'Content-Type': match[3] === 'manifest.json' ? 'application/json' : 'application/octet-stream',
                'Content-Disposition': `attachment; filename="${match[3]}"`, 'Cache-Control': 'no-store'});
            fs.createReadStream(asset, {fd, autoClose: true}).on('error', () => response.destroy()).pipe(response);
        } catch (error) {
            // Public errors are bounded and scrubbed; no request headers/body are logged.
            json(response, error.status || 400, {error: task.sanitize(error.message)});
        }
    });
    server.requestTimeout = 15000;
    server.headersTimeout = 10000;
    return {server, task};
}
function coordinator(config, task, dependencies = {}) {
    const request = dependencies.fetch || fetch;
    const terminal = [STATUS.COMPLETED, STATUS.FAILED, STATUS.CANCELED];
    let stopped = false, terminalAt = null, busy = false;
    // Same webhook ClusterODX uses for NodeODX workers. It carries no Authorization header: the
    // per-job token and exact pending job/task identity in the body are the credentials.
    const registration = {hostname: config.advertisedHost, port: config.advertisedPort, token: config.apiCapability,
        tapisJobUuid: config.jobId, registrationUuid: config.taskId,
        role: 'nodesplat', nodeReady: true};
    async function register() {
        const response = await request(config.callbackUrl + '/webhook/register-node', {method: 'POST', redirect: 'error',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify(registration), signal: AbortSignal.timeout(10000)});
        if (!response.ok) throw new Error('ClusterODX registration unavailable');
    }
    async function tick() {
        if (busy || stopped) return {stopped};
        busy = true;
        try {
            if (Date.now() >= config.leaseDeadline) { task.cancel(); stopped = true; return {stopped}; }
            // Sent on every tick: a ClusterODX restart drops its in-memory route, so the next
            // registration re-establishes it. Failures are retried on the next tick.
            try { await register(); } catch (_) { /* retry next tick */ }
            const info = task.info();
            if (task.record?.removed) stopped = true;
            else if (info && terminal.includes(info.status.code)) {
                // Grace fallback when ClusterODX never calls /task/remove after handoff.
                terminalAt ??= Date.now();
                if (Date.now() - terminalAt >= config.handoffMs) stopped = true;
            }
        } finally { busy = false; }
        return {stopped};
    }
    return {tick, get stopped() { return stopped; }};
}
async function main() {
    process.umask(0o077);
    const config = load();
    const {server, task} = createServer(config);
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(config.port, config.host, resolve); });
    const callbacks = coordinator(config, task);
    let closing = false;
    async function tick() {
        await callbacks.tick();
        if (callbacks.stopped && !closing) {
            closing = true;
            if (task.child) { task.cancel(); await task.done; }
            task.syncConsole();
            clearInterval(timer);
            server.close();
            server.closeIdleConnections();
        }
    }
    const timer = setInterval(tick, config.heartbeatMs);
    await tick();
    for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, async () => {
        task.cancel();
        if (task.done) await task.done;
        clearInterval(timer); server.close(); server.closeIdleConnections();
    });
}
if (require.main === module) main().catch(() => { console.error('NodeSplat failed to start; check required operator configuration and storage.'); process.exitCode = 1; });
module.exports = {createServer, coordinator, authorized};
