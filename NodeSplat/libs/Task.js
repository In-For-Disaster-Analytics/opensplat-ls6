'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {UUID} = require('../config');
const files = require('./files');
const runner = require('./opensplatRunner');
const STATUS = Object.freeze({QUEUED: 10, RUNNING: 20, FAILED: 30, COMPLETED: 40, CANCELED: 50});
const TERMINAL = new Set([STATUS.FAILED, STATUS.COMPLETED, STATUS.CANCELED]);
function settings(value) {
    if (!value || Object.keys(value).some(key => !['num_iterations', 'image_size'].includes(key))) throw new Error('Invalid training settings');
    const {num_iterations, image_size} = value;
    if (!Number.isInteger(num_iterations) || num_iterations < 1 || num_iterations > 1000 || !Number.isInteger(image_size) || image_size < 0 || image_size > 4096 || (image_size > 0 && image_size < 16)) throw new Error('Invalid training settings');
    return {num_iterations, image_size};
}
function requestBody(body, config) {
    if (!body || Object.keys(body).some(key => !['run_id', 'source_task_id', 'manifest_sha256', 'settings', 'set-uuid'].includes(key))) throw new Error('Unknown task field');
    if (body.run_id !== config.runId || body['set-uuid'] !== config.taskId || !UUID.test(body.source_task_id || '') || !/^[a-f0-9]{64}$/.test(body.manifest_sha256 || '')) throw new Error('Task identity does not match this allocation');
    return {run_id: body.run_id, source_task_id: body.source_task_id, manifest_sha256: body.manifest_sha256,
        settings: settings(body.settings), 'set-uuid': body['set-uuid']};
}
class Task {
    constructor(config, dependencies = {}) {
        this.config = config;
        this.startProcess = dependencies.startProcess || runner.start;
        this.outputDir = files.directory(config.outputRoot, [config.runId], true);
        this.workDir = files.directory(config.workRoot, [config.runId], true);
        this.recordFile = path.join(this.outputDir, 'worker-state.json');
        this.consoleFile = path.join(this.outputDir, 'console.txt');
        this.record = null;
        this.child = null;
        this.cancelRequested = false;
        this.logBytes = 0;
        this.truncated = false;
        this.lastLog = '';
        if (fs.existsSync(this.consoleFile)) {
            files.noLinks(this.consoleFile);
            this.logBytes = fs.statSync(this.consoleFile).size;
            if (this.logBytes > config.maxLogBytes) throw new Error('Existing console exceeds configured bound');
        } else fs.closeSync(fs.openSync(this.consoleFile, 'wx', 0o600));
        if (fs.existsSync(this.recordFile)) {
            files.regular(this.outputDir, 'worker-state.json', 1024 * 1024);
            this.record = JSON.parse(fs.readFileSync(this.recordFile, 'utf8'));
            if (this.record.uuid !== config.taskId || this.record.run_id !== config.runId || this.record.tapis_job_uuid !== config.jobId || this.record.profile_id !== config.profileId) throw new Error('Stored allocation identity mismatch');
            this.truncated = !!this.record.truncated;
            if (!TERMINAL.has(this.record.status.code)) {
                this.update({status: {code: STATUS.FAILED}, phase: 'failed', error: 'Worker restarted before training completed.', ended_at: Date.now()});
                this.append('Worker restarted; this attempt will not retrain automatically.');
            }
        }
    }
    sanitize(value) {
        let result = String(value).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g, '');
        for (const secret of [this.config.apiCapability, this.config.registrationSecret]) result = result.split(secret).join('[REDACTED]');
        for (const root of [this.config.inputRoot, this.config.outputRoot, this.config.workRoot]) result = result.split(root).join('[storage]');
        result = result.replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[REDACTED JWT]')
            .replace(/((?:authorization|token|secret|password|capability)\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+/gi, '$1[REDACTED]');
        return result.slice(0, 16384);
    }
    append(value) {
        if (this.truncated) return;
        const line = this.sanitize(value);
        const notice = '[NodeSplat console capture limit reached; training continues.]\n';
        let bytes = Buffer.from(line + '\n');
        if (this.logBytes + bytes.length + Buffer.byteLength(notice) > this.config.maxLogBytes) {
            bytes = Buffer.from(notice);
            this.truncated = true;
        }
        const fd = fs.openSync(this.consoleFile, fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_NOFOLLOW);
        try { fs.writeSync(fd, bytes); } finally { fs.closeSync(fd); }
        this.logBytes += bytes.length;
        if (this.record && this.truncated) this.update({truncated: true});
        const match = line.match(/(?:iteration|iter(?:ation)?s?|step)\s*[:#=]?\s*(\d+)\s*(?:\/|of)\s*(\d+)/i);
        if (this.record && match) {
            const iteration = Number(match[1]), total = Number(match[2]);
            if (total === this.record.request.settings.num_iterations && iteration >= 0 && iteration <= total) this.update({phase: 'training', progress: {iteration, total}});
        }
        if (this.record && /\[opensplat-ls6\] starting /.test(line)) this.update({phase: 'training'});
    }
    update(patch) {
        this.record = {...this.record, ...patch, updated_at: new Date().toISOString()};
        files.atomic(this.recordFile, JSON.stringify(this.record));
    }
    async validateInput(request) {
        const input = files.directory(this.config.inputRoot, [this.config.runId, 'input']);
        const manifest = files.regular(input, 'webodm-input.json', 8 * 1024 * 1024);
        if (await files.hash(manifest.path) !== request.manifest_sha256) throw new Error('Input manifest checksum mismatch');
        const data = JSON.parse(fs.readFileSync(manifest.path, 'utf8'));
        if (data.schema_version !== 1 || data.input_format !== 'webodm-assets' || data.task_id !== request.source_task_id || data.image_size !== request.settings.image_size) throw new Error('Input manifest identity/settings mismatch');
        if (!Array.isArray(data.images) || !data.images.length || data.images.length > this.config.maxImages) throw new Error('Invalid image count');
        if (!Array.isArray(data.rtc_offset) || data.rtc_offset.length !== 2 || !data.rtc_offset.every(Number.isFinite)) throw new Error('Invalid coordinate offset');
        const seen = new Set(), names = new Set();
        const paths = [data.cameras_path, data.shots_path, data.point_cloud_path];
        for (const image of data.images) {
            if (!image || typeof image.filename !== 'string' || path.basename(image.filename) !== image.filename || !/\.jpe?g$/i.test(image.filename) || names.has(image.filename)) throw new Error('Invalid image manifest');
            names.add(image.filename); paths.push(image.path);
        }
        let total = manifest.stat.size;
        for (const relative of paths) {
            if (seen.has(relative) || relative === 'webodm-input.json') throw new Error('Duplicate input asset');
            seen.add(relative);
            total += files.regular(input, relative, this.config.maxInputBytes).stat.size;
            if (total > this.config.maxInputBytes) throw new Error('Input byte limit exceeded');
        }
        return input;
    }
    async create(body) {
        const request = requestBody(body, this.config);
        const fingerprint = crypto.createHash('sha256').update(JSON.stringify(request)).digest('hex');
        if (this.creating) { const error = new Error('Task creation is in progress'); error.status = 409; throw error; }
        if (this.record) {
            if (this.record.request_hash !== fingerprint) { const error = new Error('Attempt already exists with different inputs'); error.status = 409; throw error; }
            return {uuid: this.config.taskId};
        }
        this.creating = true;
        try {
            const input = await this.validateInput(request);
            this.update({schema_version: 1, uuid: this.config.taskId, run_id: this.config.runId, source_task_id: request.source_task_id,
                tapis_job_uuid: this.config.jobId, profile_id: this.config.profileId, request, request_hash: fingerprint,
                status: {code: STATUS.QUEUED}, phase: 'preparing', progress: null, error: null,
                started_at: Date.now(), result_ready: false, truncated: false});
            this.append('NodeSplat accepted the prepared snapshot; preparing training inputs.');
            this.done = this.run(request, input);
            return {uuid: this.config.taskId};
        } finally { this.creating = false; }
    }
    consume(stream) {
        let pending = '';
        stream.setEncoding('utf8');
        stream.on('data', chunk => {
            pending += chunk;
            const parts = pending.split(/[\r\n]/);
            pending = parts.pop();
            for (const line of parts) if (line) this.append(line);
            if (pending.length > 16384) { this.append(pending.slice(0, 16384) + ' [line clipped]'); pending = ''; }
        });
        stream.on('end', () => { if (pending) this.append(pending); });
    }
    async run(request, input) {
        try {
            this.child = this.startProcess(this.config, request, input, this.workDir);
            this.update({status: {code: STATUS.RUNNING}});
            this.consume(this.child.stdout); this.consume(this.child.stderr);
            const {code} = await new Promise((resolve, reject) => {
                this.child.once('error', reject);
                this.child.once('close', (code, signal) => resolve({code, signal}));
            });
            this.child = null;
            if (this.cancelRequested) {
                this.append('Training process stopped; allocation cancellation is tracked by ClusterODX.');
                this.update({status: {code: STATUS.CANCELED}, phase: 'canceled', ended_at: Date.now()});
            } else if (code !== 0) throw new Error('OpenSplat preparation or training failed. Inspect this attempt’s console.');
            else {
                this.update({phase: 'publishing'});
                await this.publish(request, input);
                this.append('Training result published; waiting for ClusterODX handoff.');
                this.update({status: {code: STATUS.COMPLETED}, phase: 'result_ready', result_ready: true, ended_at: Date.now()});
            }
        } catch (error) {
            this.child = null;
            this.append('NodeSplat failed: ' + error.message);
            this.update({status: {code: STATUS.FAILED}, phase: 'failed', error: this.sanitize(error.message), ended_at: Date.now()});
        }
        this.syncConsole();
    }
    async publish(request, input) {
        const output = files.directory(this.workDir, ['output']);
        const ply = files.regular(output, `opensplat-${this.config.jobId}.ply`, this.config.maxResultBytes);
        const provenanceFile = files.regular(output, `opensplat-${this.config.jobId}.manifest.json`, 8 * 1024 * 1024);
        const provenance = JSON.parse(fs.readFileSync(provenanceFile.path, 'utf8'));
        const sha256 = await files.hash(ply.path);
        if (provenance.tapis_job_uuid !== this.config.jobId || provenance.app?.id !== this.config.appId || provenance.app?.version !== this.config.appVersion || provenance.preparation?.task_id !== request.source_task_id || provenance.num_iterations !== request.settings.num_iterations || provenance.output?.sha256 !== sha256 || provenance.output?.bytes !== ply.stat.size) throw new Error('Training artifact provenance mismatch');
        const prefix = Buffer.alloc(Math.min(ply.stat.size, 1024 * 1024));
        const fd = fs.openSync(ply.path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
        try { fs.readSync(fd, prefix, 0, prefix.length, 0); } finally { fs.closeSync(fd); }
        if (!prefix.subarray(0, 4).equals(Buffer.from('ply\n')) || !prefix.includes(Buffer.from('end_header\n'))) throw new Error('Invalid PLY result');
        const manifest = {...provenance, schema_version: 1, run_id: this.config.runId, source_task_id: request.source_task_id,
            cluster_task_uuid: this.config.taskId, tapis_job_uuid: this.config.jobId, profile_id: this.config.profileId,
            app: {id: this.config.appId, version: this.config.appVersion}, settings: request.settings,
            input_project: input, output: {bytes: ply.stat.size, sha256}};
        await files.publish(ply.path, path.join(this.outputDir, 'model.ply'));
        files.atomic(path.join(this.outputDir, 'manifest.json'), JSON.stringify(manifest, null, 2));
    }
    syncConsole() {
        const fd = fs.openSync(this.consoleFile, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
        try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    }
    info() {
        if (!this.record) return null;
        const {uuid, run_id, source_task_id, tapis_job_uuid, profile_id, status, phase, progress, error, result_ready, updated_at, truncated} = this.record;
        return {uuid, run_id, source_task_id, tapis_job_uuid, profile_id, status, phase, progress, error, result_ready, updated_at, truncated,
            processingTime: (this.record.ended_at || Date.now()) - this.record.started_at};
    }
    output(line) {
        if (!Number.isSafeInteger(line) || line < 0) throw new Error('Invalid console line offset');
        files.noLinks(this.consoleFile);
        const lines = fs.readFileSync(this.consoleFile, 'utf8').split('\n');
        if (lines.at(-1) === '') lines.pop();
        const result = []; let bytes = 0;
        for (const value of lines.slice(line, line + 500)) {
            const size = Buffer.byteLength(value) + 1;
            if (bytes + size > 256 * 1024) break;
            result.push(value); bytes += size;
        }
        return result;
    }
    cancel() {
        if (!this.record) return {success: true};
        if (TERMINAL.has(this.record.status.code)) return {success: true};
        this.cancelRequested = true;
        this.update({phase: 'canceling'});
        if (this.child) {
            const pid = this.child.pid;
            try { process.kill(-pid, 'SIGTERM'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
            const timer = setTimeout(() => {
                if (this.child?.pid === pid) {
                    try { process.kill(-pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') this.append('Unable to stop training process group.'); }
                }
            }, 10000);
            timer.unref();
        }
        return {success: true};
    }
    download(asset) {
        if (!['model.ply', 'manifest.json', 'console.txt'].includes(asset)) return null;
        if (asset !== 'console.txt' && !this.record?.result_ready) return null;
        const target = path.join(this.outputDir, asset);
        if (!fs.existsSync(target)) return null;
        files.noLinks(target);
        const stat = fs.statSync(target);
        if (!stat.isFile() || stat.size > (asset === 'console.txt' ? this.config.maxLogBytes : this.config.maxResultBytes)) throw new Error('Invalid artifact');
        return target;
    }
}
module.exports = {Task, STATUS, settings, requestBody};
