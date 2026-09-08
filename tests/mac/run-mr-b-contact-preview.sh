#!/bin/bash
set -euo pipefail
# Separate process/preferences from the earlier preview Rex may still have open.
export MR_B_PREVIEW_APP=MrBContactPreview
export MR_B_PREVIEW_BUNDLE=Rex.Review-Today.MrBContactPreview
exec bash "$(dirname "$0")/run-mr-b-preview.sh"
