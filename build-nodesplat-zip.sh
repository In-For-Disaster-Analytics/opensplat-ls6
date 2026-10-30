#!/usr/bin/env bash
# Build the NodeSplat candidate ZIP. Never uploads or registers anything.
# ZIP layout: <root>/NodeSplat and <root>/opensplat-ls6 (entry sets NODESPLAT_LAUNCHER).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PACKAGE_NAME=${PACKAGE_NAME:-nodesplat-ls6-candidate.zip}
NODESPLAT_DIR=${NODESPLAT_DIR:-$HERE/NodeSplat}

python3 -m json.tool "$HERE/app.nodesplat.json" >/dev/null
[[ -f "$NODESPLAT_DIR/index.js" ]] || { echo "NodeSplat sources not found at $NODESPLAT_DIR" >&2; exit 1; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/NodeSplat" "$STAGE/opensplat-ls6/images"
cp "$HERE/app.nodesplat.json" "$STAGE/app.json"
cp "$HERE/nodesplat_entry.sh" "$STAGE/tapisjob_app.sh"
cp "$NODESPLAT_DIR/package.json" "$NODESPLAT_DIR/index.js" "$NODESPLAT_DIR/config.js" "$STAGE/NodeSplat/"
cp -R "$NODESPLAT_DIR/libs" "$STAGE/NodeSplat/libs"
# The launcher reads app.json beside itself for its default version.
cp "$HERE/app.nodesplat.json" "$STAGE/opensplat-ls6/app.json"
(cd "$HERE" && cp tapisjob_app.sh stage_project.py validate_project.py validate_artifact.py webodm_input.py \
  prepare_webodm.py webodm_export.py validate_colmap.py WEBODM-LICENSE.txt THIRD-PARTY.md "$STAGE/opensplat-ls6/")
cp "$HERE/images/opensplat-pins.env" "$STAGE/opensplat-ls6/images/"
chmod 0755 "$STAGE/tapisjob_app.sh" "$STAGE/opensplat-ls6/tapisjob_app.sh"

rm -f -- "$HERE/$PACKAGE_NAME"
(cd "$STAGE" && zip -q -r "$HERE/$PACKAGE_NAME" . -x '*.pyc' -x '__pycache__/*')
unzip -tq "$HERE/$PACKAGE_NAME"
echo "Created $PACKAGE_NAME ($(du -h "$HERE/$PACKAGE_NAME" | awk '{print $1}')); not uploaded or registered."
