'use strict';
const path = require('node:path');
const { URL } = require('node:url');
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function required(env, name) {
    const value = env[name];
    if (!value || typeof value !== 'string') throw new Error(`${name} is required`);
    return value;
}
function integer(env, key, fallback, min, max) {
    const raw = env[key] === undefined ? fallback : env[key];
    const value = Number(raw);
    if (!Number.isSafeInteger(value) || value < min || value > max) throw new Error(`Invalid ${key}`);
    return value;
}
function load(env = process.env) {
    if (env.NODESPLAT_ENABLED !== 'YES') throw new Error('NodeSplat is disabled; set NODESPLAT_ENABLED=YES explicitly');
    const config = {env};
    for (const [key, name] of Object.entries({runId:'RUN_ID', taskId:'CLUSTER_TASK_ID', jobId:'TAPIS_JOB_ID'})) {
        config[key] = required(env, `NODESPLAT_${name}`);
        if (!UUID.test(config[key]) && !(key === 'jobId' && /^[A-Za-z0-9._-]{1,200}$/.test(config[key]))) throw new Error(`Invalid ${name}`);
    }
    for (const [key, name] of Object.entries({profileId:'PROFILE_ID', appId:'APP_ID', appVersion:'APP_VERSION', host:'BIND_HOST', apiCapability:'API_CAPABILITY'})) config[key] = required(env, `NODESPLAT_${name}`);
    if (!/^[A-Za-z0-9_-]{43,128}$/.test(config.apiCapability)) throw new Error('Invalid scoped capability');
    for (const [key, name] of Object.entries({inputRoot:'INPUT_ROOT', outputRoot:'OUTPUT_ROOT', workRoot:'WORK_ROOT'})) {
        config[key] = required(env, `NODESPLAT_${name}`);
        if (!path.isAbsolute(config[key])) throw new Error(`${name} must be absolute`);
    }
    config.port = integer(env, 'NODESPLAT_PORT', undefined, 1, 65535);
    config.publicUrl = required(env, 'NODESPLAT_PUBLIC_URL');
    config.callbackUrl = required(env, 'NODESPLAT_CALLBACK_URL').replace(/\/$/, '');
    for (const value of [config.publicUrl, config.callbackUrl]) {
        const url = new URL(value);
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Invalid service URL');
    }
    // The registration webhook reports where ClusterODX should connect: host and port only.
    const advertised = new URL(config.publicUrl);
    if (advertised.pathname !== '/') throw new Error('Invalid service URL');
    config.advertisedHost = advertised.hostname;
    config.advertisedPort = Number(advertised.port || (advertised.protocol === 'https:' ? 443 : 80));
    config.maxLogBytes = integer(env, 'NODESPLAT_MAX_LOG_BYTES', 50 * 1024 * 1024, 1024, 50 * 1024 * 1024);
    config.maxInputBytes = integer(env, 'NODESPLAT_MAX_INPUT_BYTES', 10 * 1024 ** 3, 1, 1024 ** 4);
    config.maxImages = integer(env, 'NODESPLAT_MAX_IMAGES', 2000, 1, 20000);
    config.maxResultBytes = integer(env, 'NODESPLAT_MAX_RESULT_BYTES', 8 * 1024 ** 3, 1, 1024 ** 4);
    config.heartbeatMs = 30000;
    config.handoffMs = 600000;
    config.leaseDeadline = integer(env, 'NODESPLAT_LEASE_DEADLINE', undefined, 1, Number.MAX_SAFE_INTEGER) * 1000;
    if (config.leaseDeadline <= Date.now()) throw new Error('Worker lease expired');
    // Operator-set (never request input). Repo layout: NodeSplat sits beside tapisjob_app.sh.
    config.launcher = env.NODESPLAT_LAUNCHER || path.join(__dirname, '..', 'tapisjob_app.sh');
    if (!path.isAbsolute(config.launcher)) throw new Error('NODESPLAT_LAUNCHER must be absolute');
    return config;
}
module.exports = {load, UUID};
