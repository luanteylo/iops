#!/usr/bin/env bash
# Generate the IOPS API reference into static/api/ using pdoc.
#
# The output is committed-free by design: it's regenerated from docstrings
# on every site build. Hugo then serves it at /api/.
#
# Requirements: pdoc (pip install pdoc), run from the project root.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/static/api"

cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python}"
if ! "${PYTHON}" -c "import pdoc" 2>/dev/null; then
    echo "pdoc not found in '${PYTHON}'. Install with: ${PYTHON} -m pip install pdoc" >&2
    echo "Or set PYTHON to a venv interpreter that has pdoc, e.g.:" >&2
    echo "  PYTHON=~/.venvs/iops_env/bin/python $0" >&2
    exit 1
fi

echo "Generating API reference into ${OUT_DIR}"
rm -rf "${OUT_DIR}"
"${PYTHON}" -m pdoc -o "${OUT_DIR}" iops

echo "Done. Browse at http://localhost:1313/api/ when running 'hugo serve'."
