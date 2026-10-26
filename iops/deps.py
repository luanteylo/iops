"""
Catalog of IOPS optional dependencies.

Every optional feature (Parquet sinks, Bayesian search, watch mode, plot export,
gallery downscaling, Studio) is backed by a package that is not installed with
the core. This module is the single source of truth for which those are, what
they enable, and whether they are importable, so the `iops deps` command and the
modules that gate on availability cannot disagree.

Extras listed here must match [project.optional-dependencies] in pyproject.toml.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Tuple

PACKAGE_NAME = "iops-benchmark"


@dataclass(frozen=True)
class OptionalDependency:
    """One entry of [project.optional-dependencies] and what it buys the user."""

    extra: str      # name of the pip extra, e.g. "parquet"
    package: str    # distribution name, e.g. "pyarrow"
    module: str     # top-level import name, which is not always the package name
    enables: str    # user-facing description of what stops working without it


OPTIONAL_DEPENDENCIES: Tuple[OptionalDependency, ...] = (
    OptionalDependency(
        extra="bayesian",
        package="scikit-optimize",
        module="skopt",
        enables="benchmark.search_method: bayesian",
    ),
    OptionalDependency(
        extra="parquet",
        package="pyarrow",
        module="pyarrow",
        enables="output.sink.type: parquet",
    ),
    OptionalDependency(
        extra="watch",
        package="rich",
        module="rich",
        enables="iops find --watch, progress bars",
    ),
    OptionalDependency(
        extra="plots",
        package="kaleido",
        module="kaleido",
        enables="iops report --export-plots",
    ),
    OptionalDependency(
        extra="gallery",
        package="pillow",
        module="PIL",
        enables="reporting.gallery.max_width downscaling",
    ),
    OptionalDependency(
        extra="studio",
        package="nicegui",
        module="nicegui",
        enables="iops studio",
    ),
)


def get(extra: str) -> OptionalDependency:
    """Look up a dependency by its extra name."""
    for dep in OPTIONAL_DEPENDENCIES:
        if dep.extra == extra:
            return dep
    known = ", ".join(d.extra for d in OPTIONAL_DEPENDENCIES)
    raise KeyError(f"Unknown optional dependency '{extra}'. Known extras: {known}")


@lru_cache(maxsize=None)
def is_available(extra: str) -> bool:
    """
    Report whether the package behind an extra is installed, without loading it.

    This runs on every IOPS startup, once per gate, so it locates the module
    rather than importing it: importing scikit-optimize alone costs most of a
    second (it pulls in sklearn and scipy), and paying that to set a boolean
    delayed every command including `iops --version`.

    The trade-off is that a package which is present but fails on import counts
    as available here. That is safe for the gates, because the code that goes on
    to use a package imports it for real and raises a clear error if it cannot.
    Use is_importable() when the answer itself is the product, as it is for
    `iops deps`.
    """
    import importlib.util

    try:
        return importlib.util.find_spec(get(extra).module) is not None
    except (ImportError, AttributeError, ValueError):
        # A missing parent package raises, and a module already imported without
        # a spec has none to find. Either way it is not usable.
        return False


@lru_cache(maxsize=None)
def is_importable(extra: str) -> bool:
    """
    Report whether the package behind an extra actually imports.

    Slower than is_available() but authoritative: a package recorded as
    installed but broken counts as missing, which is what a user running
    `iops deps` to diagnose an environment needs to see.
    """
    import importlib

    try:
        importlib.import_module(get(extra).module)
        return True
    except ImportError:
        return False


def installed_version(extra: str) -> Optional[str]:
    """Return the installed version of an extra's package, or None if absent."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(get(extra).package)
    except PackageNotFoundError:
        # Importable without distribution metadata (vendored, or on PYTHONPATH).
        return "unknown" if is_importable(extra) else None


def missing_extras() -> List[str]:
    """Return the extras whose package does not import, in catalog order."""
    return [dep.extra for dep in OPTIONAL_DEPENDENCIES if not is_importable(dep.extra)]


def install_hint(extras: List[str]) -> str:
    """
    Return the pip command that installs the given extras.

    The package spec is quoted because zsh, the default shell on macOS and on
    many Linux setups, treats the square brackets of an extra as a glob and
    fails with "no matches found" on the unquoted form.
    """
    return f'pip install "{PACKAGE_NAME}[{",".join(extras)}]"'


def format_status(missing_only: bool = False) -> str:
    """Render the dependency table shown by `iops deps`."""
    rows = []
    for dep in OPTIONAL_DEPENDENCIES:
        available = is_importable(dep.extra)
        if missing_only and available:
            continue
        status = installed_version(dep.extra) if available else "not installed"
        rows.append((dep.extra, dep.package, status, dep.enables))

    if not rows:
        return "All optional dependencies are installed."

    headers = ("EXTRA", "PACKAGE", "STATUS", "ENABLES")
    widths = [
        max(len(headers[i]), max(len(row[i]) for row in rows))
        for i in range(3)
    ]

    lines = [
        f"{headers[0]:<{widths[0]}}  {headers[1]:<{widths[1]}}  "
        f"{headers[2]:<{widths[2]}}  {headers[3]}"
    ]
    for extra, package, status, enables in rows:
        lines.append(
            f"{extra:<{widths[0]}}  {package:<{widths[1]}}  "
            f"{status:<{widths[2]}}  {enables}"
        )
    return "\n".join(lines)
