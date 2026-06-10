"""Small filesystem helpers shared across modules."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path | str, data: Any, **json_kwargs: Any) -> None:
    """
    Write JSON to path atomically: write to a temporary file in the same
    directory, then os.replace() it over the destination.

    IOPS metadata files (__iops_index.json, __iops_status.json, ...) are read
    by concurrent processes such as iops find and watch mode while the runner
    rewrites them. A plain open(path, "w") truncates first, so readers can
    observe empty or partially written JSON. os.replace() is atomic on POSIX,
    so readers always see either the old or the new complete file.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, **json_kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
