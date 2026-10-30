'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
function contained(root, target) {
    const relative = path.relative(root, target);
    return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}
function noLinks(target) {
    const absolute = path.resolve(target);
    let current = path.parse(absolute).root;
    for (const part of absolute.slice(current.length).split(path.sep).filter(Boolean)) {
        current = path.join(current, part);
        if (fs.lstatSync(current).isSymbolicLink()) throw new Error('Symbolic links are not permitted');
    }
    return absolute;
}
function directory(root, components = [], create = false) {
    root = fs.realpathSync(root);
    noLinks(root);
    const target = path.join(root, ...components);
    if (!contained(root, target)) throw new Error('Directory escapes root');
    if (create) fs.mkdirSync(target, {recursive: true, mode: 0o700});
    noLinks(target);
    if (!fs.statSync(target).isDirectory()) throw new Error('Expected directory');
    return target;
}
function regular(root, relative, maxBytes = Number.MAX_SAFE_INTEGER) {
    if (typeof relative !== 'string' || !relative || relative.includes('\\') || relative.includes('\0') || path.isAbsolute(relative) || relative.split('/').includes('..')) throw new Error('Invalid asset path');
    const target = path.join(root, relative);
    if (!contained(root, target)) throw new Error('Asset escapes root');
    noLinks(target);
    const stat = fs.statSync(target);
    if (!stat.isFile() || stat.size === 0 || stat.size > maxBytes) throw new Error('Invalid asset size or type');
    return {path: target, stat};
}
function atomic(file, bytes) {
    if (fs.existsSync(file) && fs.lstatSync(file).isSymbolicLink()) throw new Error('Refusing linked output');
    const temporary = `${file}.${crypto.randomUUID()}.tmp`;
    const fd = fs.openSync(temporary, 'wx', 0o600);
    try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, file);
    const dir = fs.openSync(path.dirname(file), 'r');
    try { fs.fsyncSync(dir); } finally { fs.closeSync(dir); }
}
async function hash(file) {
    const digest = crypto.createHash('sha256');
    for await (const chunk of fs.createReadStream(file, {flags: fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW})) digest.update(chunk);
    return digest.digest('hex');
}
async function publish(source, destination) {
    const temporary = `${destination}.${crypto.randomUUID()}.tmp`;
    await fs.promises.copyFile(source, temporary, fs.constants.COPYFILE_EXCL);
    fs.chmodSync(temporary, 0o600);
    const fd = fs.openSync(temporary, 'r');
    try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    if (fs.existsSync(destination)) throw new Error('Refusing to overwrite result');
    fs.renameSync(temporary, destination);
}
module.exports = {directory, regular, atomic, hash, publish, noLinks};
