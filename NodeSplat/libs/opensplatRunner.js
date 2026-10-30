'use strict';
const {spawn} = require('node:child_process');
const path = require('node:path');
// This is operator configuration, not task input. Never inherit the user JWT or
// callback/API credentials into preparation, Apptainer or OpenSplat.
const ALLOWED = new Set(['PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'TMPDIR', 'SCRATCH', 'LD_LIBRARY_PATH',
    'CUDA_VISIBLE_DEVICES', 'SLURM_JOB_ID', 'SLURM_JOB_PARTITION', 'SLURM_JOB_ACCOUNT', 'SLURM_NODELIST',
    'OPENSPLAT_SIF_PATH', 'OPENSPLAT_PREPARE_SIF', 'OPENSPLAT_PREPARE_SHA256', 'OPENSPLAT_PREPARE_SECONDS',
    'OPENSPLAT_MAX_PREPARE_FILE_KIB', 'OPENSPLAT_CUDA_IMAGE', 'OPENSPLAT_SIF_CACHE_DIR', 'OPENSPLAT_REFRESH_SIF']);
function environment(config, input, work) {
    const env = {};
    for (const key of ALLOWED) if (config.env[key] !== undefined) env[key] = config.env[key];
    Object.assign(env, {OPENSPLAT_PROFILE: 'cuda', OPENSPLAT_CENTER: '0', OPENSPLAT_OUTPUT_FORMAT: 'ply',
        OPENSPLAT_STREAM_LOG: '1', OPENSPLAT_IMPORT_PATH_ROOTS: config.inputRoot,
        OPENSPLAT_MAX_IMAGES: String(config.maxImages), OPENSPLAT_MAX_INPUT_BYTES: String(config.maxInputBytes),
        OPENSPLAT_APP_ID: config.appId, OPENSPLAT_APP_VERSION: config.appVersion,
        _tapisJobUUID: config.jobId, _tapisJobWorkingDir: work,
        _tapisExecSystemOutputDir: path.join(work, 'output')});
    return env;
}
function start(config, request, input, work) {
    return spawn('bash', [config.launcher, input, String(request.settings.num_iterations)], {
        cwd: work, env: environment(config, input, work), detached: true,
        stdio: ['ignore', 'pipe', 'pipe']
    });
}
module.exports = {start, environment};
