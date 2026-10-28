"""Check generated COLMAP files before allowing training."""
import argparse
import struct
from pathlib import Path


def validate(root, max_bytes):
    root = Path(root)
    files = list(root.rglob('*'))
    if any(p.is_symlink() for p in files):
        raise ValueError('generated COLMAP contains symlinks')
    if sum(p.stat().st_size for p in files if p.is_file()) > max_bytes:
        raise ValueError('prepared output exceeds byte limit')
    for name in ('cameras.bin', 'images.bin', 'points3D.bin'):
        p = root / 'sparse/0' / name
        with p.open('rb') as f:
            count = f.read(8)
        if len(count) != 8 or struct.unpack('<Q', count)[0] == 0 or p.stat().st_size <= 8:
            raise ValueError('empty or truncated COLMAP ' + name)
    if not (root / 'images').is_dir() or not any((root / 'images').iterdir()):
        raise ValueError('missing COLMAP images')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project')
    parser.add_argument('--max-bytes', type=int, required=True)
    args = parser.parse_args()
    validate(args.project, args.max_bytes)
