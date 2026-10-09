#!/usr/bin/env bash
set -euo pipefail

PACKAGE_NAME=${PACKAGE_NAME:-opensplat-ls6.zip}
REMOTE_DIR=${REMOTE_DIR:-/corral/utexas/BCS26030/NodeODX}
REMOTE_SSH_TARGET=${REMOTE_SSH_TARGET:-ls6}
REMOTE_GROUP=${REMOTE_GROUP:-G-829114}
SKIP_UPLOAD=${SKIP_UPLOAD:-1}

rm -f -- "$PACKAGE_NAME"
python3 -m json.tool app.json >/dev/null
python3 -m py_compile stage_project.py validate_project.py validate_artifact.py

zip -q -r "$PACKAGE_NAME" app.json tapisjob_app.sh stage_project.py validate_project.py validate_artifact.py README.md README-ZIP.md images/opensplat-pins.env images/README.md \
  -x '*.pyc' -x '__pycache__/*'
unzip -tq "$PACKAGE_NAME"

echo "Created $PACKAGE_NAME ($(du -h "$PACKAGE_NAME" | awk '{print $1}'))"
if [[ "$SKIP_UPLOAD" == "0" ]]; then
  echo "Upload requested to ${REMOTE_SSH_TARGET}:${REMOTE_DIR}/${PACKAGE_NAME}"
  REMOTE_STAGING_DIR="/tmp/${USER}/opensplat-ls6"
  REMOTE_STAGING_FILE="${REMOTE_STAGING_DIR}/${PACKAGE_NAME}"
  ssh "$REMOTE_SSH_TARGET" "mkdir -p '$REMOTE_STAGING_DIR' && rm -f '$REMOTE_STAGING_FILE'"
  scp "$PACKAGE_NAME" "${REMOTE_SSH_TARGET}:${REMOTE_STAGING_FILE}"
  ssh "$REMOTE_SSH_TARGET" "sg '$REMOTE_GROUP' -c \"mkdir -p '$REMOTE_DIR' && install -m 0640 '$REMOTE_STAGING_FILE' '$REMOTE_DIR/$PACKAGE_NAME'\""
  ssh "$REMOTE_SSH_TARGET" "rm -f '$REMOTE_STAGING_FILE'"
else
  echo "Upload skipped (SKIP_UPLOAD=$SKIP_UPLOAD)"
fi
