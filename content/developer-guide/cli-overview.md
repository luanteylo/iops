---
title: "CLI Overview"
weight: 15
---

The IOPS CLI is a git-style subcommand tool. The entry point is `iops/main.py`,
which defines all subcommands with `argparse` and dispatches each one to the
appropriate module. Use `iops <subcommand> --help` for flag-level documentation.
This page focuses on what each subcommand does and where the logic lives.

## Subcommand table

| Subcommand | Purpose | Entry function in `main.py` | Heavy lifting in |
|------------|---------|-------------------------------|------------------|
| `run` | Load config, build execution plan, run all tests, write results | `main()` dispatches to `IOPSRunner.run()` | `iops/execution/runner.py` |
| `check` | Validate a config file without executing; optionally print the resolved YAML | `main()` calls `validate_yaml_config()` or `resolve_yaml_config()` | `iops/config/loader.py` |
| `generate` | Write a starter config template (interactive wizard) | `main()` instantiates `BenchmarkWizard` | `iops/setup/wizard.py` |
| `report` | Generate an interactive HTML report from a completed run directory | `main()` calls `generate_report_from_workdir()` | `iops/reporting/report_generator.py` |
| `find` | List executions in a workdir, filter by parameter or status | `main()` calls `find_executions()` or `watch_executions()` | `iops/results/find.py`, `iops/results/watch.py` |
| `archive create` | Package a run directory into a portable `.tar.gz` | `main()` calls `create_archive()` | `iops/archive/core.py` |
| `archive extract` | Unpack an IOPS archive with checksum verification | `main()` calls `extract_archive()` | `iops/archive/core.py` |
| `cache list/show/stats/rebuild` | Inspect and manage the SQLite result cache | `main()` calls functions from `iops/cache` | `iops/cache/execution_cache.py`, `iops/cache/inspect.py`, `iops/cache/rebuild.py` |
| `convert` | Convert a JUBE XML benchmark config to IOPS YAML (requires JUBE installed) | `main()` calls `convert_jube_to_iops()` | `iops/convert/jube_converter.py` |

## How dispatch works

`parse_arguments()` in `main.py` builds an `argparse.ArgumentParser` with a
`subparsers` group. Each subcommand gets its own sub-parser. After parsing,
`main()` inspects `args.command` (and `args.archive_command` or
`args.cache_command` for nested subcommands) and calls the corresponding code
path inline or imports a module.

Two conveniences are worth knowing about:

- **YAML shorthand.** `_preprocess_args()` runs before argparse. If the first
  argument ends in `.yaml` or `.yml`, it inserts `run` automatically, so
  `iops config.yaml` works as an alias for `iops run config.yaml`.
- **Common flags.** `_add_common_args()` attaches `--log-file`, `--log-level`,
  `--no-log-terminal`, and `-v` / `--verbose` to every sub-parser so they are
  available on every subcommand.

## Usage examples

For usage examples (flags, filter syntax, output formats), refer to the User
Guide pages:

- [Running benchmarks]({{< relref "/user-guide/cli" >}})
- [Exploring results]({{< relref "/user-guide/exploring-executions" >}})
- [Reporting]({{< relref "/user-guide/reporting" >}})
- [Caching]({{< relref "/user-guide/caching" >}})
