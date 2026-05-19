---
title: "API Reference"
weight: 90
---

The IOPS API reference is generated automatically from the docstrings in the
`iops` Python package using [pdoc](https://pdoc.dev/). It covers every public
module, class, and function with their signatures, parameter descriptions, and
usage examples drawn directly from the source code.

[Browse the API reference](/api/)

## Regenerating the reference locally

The API docs are built by a helper script that runs pdoc against the installed
`iops` package and writes HTML to `static/api/`:

```bash
# Either activate the venv first:
source ~/.venvs/iops_env/bin/activate
./scripts/build_api_docs.sh

# Or point the script at a venv interpreter explicitly:
PYTHON=~/.venvs/iops_env/bin/python ./scripts/build_api_docs.sh
```

The script clears `static/api/` and regenerates it from the installed `iops`
package, so you only need to rerun it when public docstrings change. Hugo
serves the result at `/api/` once you run `hugo serve` or `hugo build`.

If `pdoc` is not installed in your venv, install it with `pip install pdoc`.

## Docstring quality drives API doc quality

pdoc renders whatever docstrings are in the source. A well-written docstring
includes a one-line summary, an `Args` block with parameter descriptions, a
`Returns` block, and at least one `Example`. The `iops/archive/__init__.py`
module has good examples to follow:

```python
def create_archive(source, output, compression="gz", ...):
    """
    Create an IOPS archive from a run directory or workdir.

    Args:
        source: Path to the run directory or workdir to archive.
        output: Path for the output archive file.
        compression: Compression type ("gz", "bz2", "xz", or "none").
        ...

    Returns:
        Path to the created archive.

    Raises:
        FileNotFoundError: If source does not exist.
        ValueError: If source is not a valid IOPS directory or no executions
                   match the filters (for partial archives).

    Example:
        >>> create_archive("./workdir/run_001", "study.tar.gz")
        PosixPath('/path/to/study.tar.gz')
    """
```

When adding a new public function or class, write the docstring before opening
a pull request. Undocumented public symbols appear in the generated reference
with no description, which is harder to fix after the fact than to write
upfront.
