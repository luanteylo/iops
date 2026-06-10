---
title: "Changelog"
weight: 40
---

All notable changes to IOPS are documented here.

## [Unreleased]

### Added

- `iops find` and watch mode now read a single run-root `__iops_status_rollup.json` aggregate instead of scanning every `exec_XXXX/repetition_N/__iops_status.json` on each refresh. This keeps them responsive on large parameter spaces (thousands of executions) and on parallel/network filesystems, where per-folder reads dominate wall-clock. The runner maintains the roll-up during the run and marks it complete when finished; watch always reads it, while `iops find` trusts it only when complete and otherwise falls back to the folder scan. The per-folder status files remain the source of truth, so older runs and archives keep working.

### Fixed

#### Search and planning
- Bayesian search no longer crashes on string (categorical) sweep variables: the nearest-valid-point mapping converted every dimension with `float()`, so any `type: str` variable with more than one value failed on the first iteration. Categorical values are now mapped to category indices for distance computation.
- Single-allocation (kickoff) mode now honors random sampling. Previously `search_method: random` with `allocation.mode: single` silently prepared and ran the entire parameter space, ignoring `n_samples`/`percentage`.
- `search_method: adaptive` is now rejected with `allocation.mode: single` (same as bayesian) instead of crashing at run start; adaptive probing cannot work in a pre-generated script.
- Constraints that reference an adaptive variable no longer abort the run during matrix generation with an undefined-variable error. They are deferred to per-probe evaluation, where the adaptive value is in scope.
- The Bayesian planner now hands out per-repetition clones of execution instances instead of mutating one shared object. Previously resource-sampling summaries collapsed to the last repetition per execution, and dry-run accounting could attribute results to the wrong execution id.
- When the Bayesian optimizer suggests an already-visited configuration, the planner now re-tells the optimizer that point's known outcome so the next suggestion actually changes; previously all retries returned the identical point and the iteration silently degraded to random sampling or triggered spurious early convergence.
- An explicit `random_seed: null` no longer crashes the Bayesian convergence fallback.

#### Execution runtime
- Parser output capture is now serialized across worker threads. With `parallel > 1`, the process-wide stdout/stderr redirection could cross-contaminate `parser_stdout`/`parser_stderr` files between tests and leave the process writing to an abandoned buffer.
- IOPS metadata files (`__iops_index.json`, `__iops_status.json`, `__iops_params.json`, run metadata) are now written atomically (temp file plus rename). Concurrent readers such as `iops find` and watch mode could previously observe truncated JSON mid-rewrite and fail or flicker.
- The local executor streams benchmark stdout/stderr directly to files instead of buffering everything in memory: verbose benchmarks no longer risk exhausting RAM, and output captured before an interrupt is preserved.
- A typo in `benchmark.cores_expr` now fails fast with a clear error instead of silently counting every test as 1 core, which effectively disabled `max_core_hours` budget enforcement. The expression is also evaluated without builtins.
- Fixed two Ctrl+C races: the interrupt handler could deadlock on the job-tracking lock, and an interrupt arriving between the shutdown check and a thread-pool submission turned a clean shutdown into a traceback.
- Dry-run reports for planners that reuse test objects (Bayesian) now snapshot execution ids and variables at collection time, fixing unique-test counts and cache-hit accounting.

#### Configuration loading
- Config blocks with a null or wrong-typed body (`sweep:`, `adaptive:`, `vars:`, `scripts:`, `command:`, `parser:`, `post:`, `constraints:`, `machines:`, and all `reporting` sub-blocks) now produce field-located validation errors instead of raw AttributeError/TypeError crashes. Commenting out a block body while leaving the key is the common trigger.
- `--machine`/`IOPS_MACHINE` with no `machines` section in the config now produces the intended friendly error instead of `KeyError: 'machines'`.
- `cache_file: null` no longer crashes; an empty `cache_file` is rejected with a clear error instead of resolving to the current directory. Templated `cache_file` paths now render strictly: an undefined variable raises a field-located error instead of silently producing a wrong path like `.db`.
- One-line script templates containing Jinja expressions (e.g. `bash {{ workdir }}/run.sh`) are no longer misclassified as file paths and rejected with "file was not found".
- `output.sink.include` now emits a warning that it is not supported instead of being silently ignored.
- `random_config.percentage` values above 1.0 are rejected with an explanation that percentage is a 0-1 fraction; previously `percentage: 50` was silently clamped to 1.0, meaning 100% sampling.
- Non-string `command.template`/`script_template` values now produce the intended "must be a string, got int" hint instead of an AttributeError.
- A script without a `name` now fails with `scripts[i].name is required` instead of a KeyError.
- Machine overrides that replace a var's `sweep` with `expr` now also clear inherited `when`/`default`, fixing a confusing validation failure for a reasonable override.
- Duplicate names within a machine-override list (`scripts`, `constraints`) now raise an error instead of silently dropping the second entry.
- `benchmark.workdir` no longer needs to pre-exist; it is created on first run as the (previously unreachable) creation logic always intended.

#### CLI, watch mode, find
- Bare `iops archive` and `iops cache` print the intended "No subcommand specified" help instead of crashing with an AttributeError.
- `iops find --interval` values below 1 are rejected; an interval of 0 previously busy-spun the CPU and disabled all keyboard controls.
- PageUp/PageDown now work in watch mode: their 4-byte escape sequences were truncated to 3 bytes and could never match, leaving a stray `~` consumed as a spurious keypress.
- The `/` go-to-test search in watch mode jumps to the correct row when completed tests are hidden (auto-enabled for runs with more than 20 tests).
- Watch mode no longer evaluates `cores_expr` text from metadata files with `eval()`; values are parsed as plain numbers.
- A held or repeated keypress can no longer starve the watch-mode data refresh; refresh is driven by a monotonic deadline.
- The `/dev/tty` keyboard fallback now also engages when stdin is closed or unusable, not only when it is a non-TTY.
- An interrupt arriving before the first watch refresh no longer raises UnboundLocalError.
- `iops find` parameter filters now match numerically and case-insensitively for booleans: `nodes=4` matches a stored `4.0`, `flag=true` matches `True`, `1e3` matches `1000.0`. The same matching is used by watch-mode filters.
- Log messages containing ` | ` (such as per-test metric summaries) no longer have their first part duplicated as a prefix on wrapped or multi-line console output.

#### Reporting
- Total core-hours in HTML reports paired each row with the wrong duration (or silently skipped rows) whenever any execution had been filtered out as failed; rows and durations are now aligned positionally.
- Benchmark name, description, variable values, hostnames, and probe-collected system strings are now HTML-escaped in report sections that previously interpolated them raw, so a value containing markup cannot break or inject into the report.
- Custom plot configurations survive report regeneration: the serialized template now includes `row_vars`, `col_var`, `aggregation`, sort options, the `bayesian_parameter_evolution` and `resource_sampling` section flags, and `best_results.min_samples`, all of which were previously dropped.
- Scatter plots with a string-typed variable as y-axis or color no longer fail; non-numeric color columns are encoded with labeled colorbars.
- The variable impact plot no longer disappears when all impacts are zero.

#### Cache
- The repetition count for cached parameter sets now counts distinct repetitions, fixing over-counting on caches built with `iops cache rebuild` (which may hold several rows per repetition).
- The objective-metric cache lookup orders entries by creation time, making the fallback deterministic, and no longer crashes on string-serialized metric values.
- Fixed a connection leak in the cache's locked-database retry path, and `iops cache rebuild` now closes its database connections.

## [3.5.7] - 2026-06-10

This release fixes a set of correctness bugs found in a code audit,
focused on silent result corruption (CSV/Parquet/SQLite sinks, execution
cache), Bayesian search direction, SLURM polling robustness on busy
clusters, and archive integrity.

### Fixed
- `iops find --watch`: keyboard controls (`q` to quit, `p` to pause, navigation) and the `--interval` refresh rate now work when standard input is not a terminal (e.g. stdin redirected, piped, or the process launched without a terminal attached to stdin). Watch mode now falls back to the controlling terminal (`/dev/tty`) for keyboard input instead of silently dropping every keypress and leaving the terminal echoing in canonical mode. The refresh interval is now driven by a monotonic deadline, so it is honored even when no keyboard is available rather than collapsing into a busy loop.

- Bayesian search: `bayesian_config.objective` now defaults to `minimize` as documented. The loader previously defaulted to `maximize`, silently optimizing in the wrong direction for configurations that omitted the field. If you relied on the undocumented default, set `objective: maximize` explicitly.

- Bayesian search: the end-of-run "Best parameters found" summary now reports the actual best point for `objective: minimize` studies. The best-value comparison was inverted, so the summary tracked the last evaluated point instead of the best one (the optimizer itself was unaffected).

- CSV results sink: extending the schema with a new column (e.g. a metric that first appears mid-run) no longer rewrites existing rows through pandas type inference. Previously the rewrite silently mutated stored values, such as `"0010"` becoming `10` and integer columns becoming floats. Existing rows are now preserved verbatim. A zero-byte results file left behind by an interrupted run no longer makes every subsequent write fail.

- SQLite results sink: rows that introduce new columns no longer abort the run with "table has no column named ...". The table schema is extended with `ALTER TABLE ADD COLUMN` instead.

- Parquet results sink: appending a row that lacks a value for an existing integer column no longer permanently upcasts the column to float; integer columns are preserved as nullable integers.

- Execution cache: numeric-looking strings are only coerced for hashing when the conversion round-trips exactly, so distinct string parameters such as `"1.1"` and `"1.10"` (version strings) or `"1e3"` no longer collapse into the same cache key and return each other's results as false cache hits. Negative integer strings now hash like their native integer counterparts.

- `iops cache create`: caches built from CSV now store the executor status under the key the runner actually reads, so cache hits report `SUCCEEDED` instead of `UNKNOWN` in status files, results, and `iops find --status` filtering. CSV cell coercion now matches runtime parameter normalization exactly (previously negative integers never produced cache hits).

- SLURM executor: a transient `squeue` failure (e.g. `slurm_load_jobs error: Socket timed out`) is no longer interpreted as "job left the queue". Previously one controller hiccup abandoned a live job: polling stopped, the job was removed from Ctrl+C cleanup tracking, and a still-running state was recorded as final. Status polling now retries on transient errors and confirms job completion via `scontrol` before finalizing.

- SLURM single-allocation mode: a transient `squeue` failure no longer fails the current test and poisons every remaining test while the allocation keeps running on the cluster. The allocation state check is also throttled to `poll_interval` (previously `squeue` was invoked twice per second for the entire run).

- SLURM executor: job ids are now parsed from multi-cluster submission output (`Submitted batch job 12345 on cluster c2`). Previously the job was marked as an error and ran untracked on the cluster.

- SLURM executor: `DEADLINE`, `REVOKED`, and `SPECIAL_EXIT` are now recognized as terminal failure states. A deadline-killed job could previously be recorded as `SUCCEEDED` when its partial output happened to parse.

- SLURM executor: the job start timestamp is now recorded when a job is already running at the first poll, fixing wrong queue-wait/run-time splits for jobs that start immediately.

- `iops archive`: partial archives (`--status`, `--params`, `--min-completed-reps`) no longer fail their own integrity verification on extraction. Checksums are now computed over the content actually stored in the archive (filtered index and included executions) instead of the unfiltered source tree.

- `iops archive create --min-completed-reps`: filtered result files are no longer empty. Repetition folder numbers (1-based) were compared against result rows using a 0-based index, so completed repetitions almost never matched.

- `iops archive extract`: extraction now applies the standard library's `data` filter, which rejects symlinks and hard links pointing outside the destination directory, absolute paths, and device nodes. The previous custom filter only inspected member names, leaving a path traversal vector via crafted symlink members, and it also skipped legitimate files whose names merely contained `..` (e.g. `results..csv`).

## [3.5.6] - 2026-06-09

### Added
- Per-execution image gallery (`reporting.gallery`) for embedding simulation thumbnails and other per-test images into the self-contained HTML report
  - Thumbnail grid grouped by execution with click-to-enlarge; images are base64-embedded so the report has no external file dependencies
  - Two discovery methods that can be combined: convention folder (auto-scans `<execution_dir>/<gallery.folder>` for files matching `pattern`) and explicit `sources` (Jinja2-templated paths resolved per execution, glob characters honored)
  - New built-in template variable `{{ artifacts_dir }}` resolves to `<execution_dir>/<gallery.folder>` (default `<execution_dir>/images`); use it in `script_template` to write images without hardcoding the folder name
  - `max_width` option (requires Pillow) downscales wide images before embedding; degrades gracefully without Pillow
  - `caption_vars` controls which parameters appear as the caption under each execution's card (defaults to `report_vars`)
  - Controlled by `reporting.sections.gallery` (default `true`); section auto-enables when images are found

- Software version capture probe (`benchmark.probes.versions`) for recording software and library versions as metadata once per execution
  - Mapping of component name to shell command (e.g. `app: "myapp --version"`); IOPS injects `__iops_atexit_versions.sh` and captures versions after the benchmark body via the exit handler, so version tools made available by the benchmark's own `module load` commands are in scope
  - Failing commands record an empty string rather than aborting the run
  - Writes `__iops_versions.json` to each repetition directory, and surfaces the captured versions as `version.<component>` columns in the results sink (CSV/Parquet/SQLite) so they can be queried alongside metrics; exclude with `output.sink.exclude: [version.*]`
  - HTML report renders a Software Versions section with a per-execution table; a prominent drift warning is shown when any component reports more than one distinct value across executions (this is the cache-mixing detector: it catches studies that mix freshly executed results with older cached results from a different software environment)
  - Controlled by `reporting.sections.versions` (default `true`); section auto-enables when version data is present

- `iops cache create` subcommand to build a cache database from a CSV file
  - `--params` and `--metrics` map CSV columns to parameters (the cache key) and metrics; each row becomes one cached execution
  - Cell values are coerced to int/float/bool where possible so they hash the same way IOPS normalizes parameters at run time
  - `--repetition-column` uses an existing column as the repetition number; otherwise repetitions are auto-numbered per unique parameter set
  - Shows a progress bar while writing entries (requires the `watch` extra for `rich`); disable with `--no-progress`
  - Imported entries are stored with `SUCCEEDED` status and work with `cache list|show|stats` and `iops run --use-cache`

- Execution Status breakdown in HTML reports, showing the count and percentage of executions by status (SUCCEEDED, FAILED, ERROR, SKIPPED, RUNNING, PENDING). Counts come from the run index and per-execution status files, so failures and skips are reported even though the results table only contains successful executions. A success-rate summary is also shown in the Execution Overview when not every execution succeeded.

- Log the execution id and repetition before each submission (e.g. `Submitting 684 (rep 1/3)`), so the execution can be correlated with the executor's submission output such as the SLURM job id.

- Highlight the actively running row in `iops find --watch` with a background color (in addition to the existing `▶` marker), making the in-progress execution easier to spot.

### Changed
- `iops archive extract` without `-o` now extracts into a folder named after the archive (e.g. `study.tar.gz` -> `./study/`) instead of scattering files into the current directory. Pass `-o PATH` to choose a different destination.

### Fixed
- Report generation no longer fails when merging resource sampling metrics for runs that use integer execution ids. The results dataframe stores `execution.execution_id` as integers while `__iops_resource_summary.csv` stores zero-padded folder-style ids (`exec_0002`), so the join raised "You are trying to merge on int64 and object columns". Both join keys are now normalized to the numeric execution id before merging.

## [3.5.5] - 2026-05-30

This release introduces declarative input files, letting benchmarks that read
parameters from disk (configuration files, problem decks, job descriptions)
generate those files from the execution context instead of relying on the
command template alone. It also gathers a set of reliability fixes around
interruption handling, report accuracy, system probing, and live monitoring,
making long campaigns on shared clusters more robust.

### Added
- Declarative input files via `scripts[].inputs` for parameter files that the benchmark reads from disk
  - Each entry declares a required `name`, required `path` (Jinja2-rendered destination), `template` (inline) or `file` (external path), and optional `mode` (octal string applied with chmod)
  - Files are rendered with the full execution context (vars, `os_env`, `execution_id`, `repetition`, etc.) and written at preparation time, so the exact input used for each run remains on disk even if the script aborts
  - Rendered paths are exposed in `script_template`, `command.template`, and `post.script` via `{{ inputs.<name>.path }}`
  - Names must be valid Python identifiers and unique within a script; Jinja2 syntax in `template` and `path` is validated at load time
  - Purely additive: existing configs without `inputs:` are unaffected

### Fixed
- Best Configurations table in HTML reports now shows the exact command recorded for each execution. It previously re-rendered the command template from the swept variables alone, so templates referencing runtime-only values such as `{{ inputs.<name>.path }}` could not be reconstructed and rendered as `[Error rendering command: ...]`. The command is now looked up from `__iops_index.json` by execution id (normalized so the integer id in the results dataframe matches the zero-padded id in the index), falling back to template rendering only when no index is available.
- Ctrl+C no longer submits a new SLURM job during shutdown. The SIGINT handler set `self.interrupted` and canceled the in-flight job, but neither `_run_sequential` nor `_run_parallel` checked that flag, so the loop fetched the next test from the planner and submitted it before exiting. Both loops now guard at the top of the iteration and again right before `_execute_and_cache` / `pool.submit`, closing the race window between `next_test()` and submission. A single Ctrl+C is now sufficient to stop the run cleanly.
- System probe no longer emits invalid `__iops_sysinfo.json` on CPU-only nodes. The GPU detection block trusted `command -v nvidia-smi` alone, but on nodes where the binary exists yet cannot reach a driver, `nvidia-smi` printed an error into the integer GPU fields, corrupting the JSON and triggering a parse warning during result collection. The probe now checks `nvidia-smi -L` first, strips newlines from all GPU fields, and validates that `gpu_count` and `gpu_memory_mib` are digits before emitting them.
- Watch mode no longer hides executions beyond the planner's estimate. In dynamic mode the live table bounded its display range by `total_expected`, so when a campaign produced more executions than estimated (common with adaptive and Bayesian probing) the extra executions existed in the data but were never rendered. The display range now extends to cover the highest existing execution id, while queued placeholders still fill up to the estimate when it is higher.

## [3.5.4] - 2026-04-28

### Added
- Parallel test execution via `benchmark.parallel` config field and `--parallel N` CLI flag
  - Run multiple tests concurrently using a thread pool (works with both local and SLURM executors)
  - Planner-aware: Exhaustive and Random support unlimited parallelism, Bayesian is capped to 1 (sequential), Adaptive parallelizes across independent probes
  - Thread-safe budget tracking, result writing, cache access, and SLURM job management
  - Incompatible with single-allocation mode (ignored with a warning)
- `BasePlanner.max_parallel()` and `BasePlanner.next_tests(n)` methods for planner parallelism negotiation
- YAML configuration section in HTML reports, showing the original config in a collapsible block
- Signal handler registration for all executors (previously SLURM-only)
- `iops cache list`, `iops cache show`, and `iops cache stats` subcommands for inspecting cache databases
  - `list` collapses entries per unique parameter hash, with averaged metrics across repetitions and `VAR=VALUE` filtering (same syntax as `iops find`)
  - `show` accepts a git-style hash prefix and prints every repetition's metrics and metadata
  - `stats` prints totals, unique parameter sets, and date range
  - All three support `--json` for scripting
- Public helpers in `iops.cache` for programmatic inspection: `list_cache_entries`, `get_cache_entry`, `get_cache_stats`, `resolve_hash_prefix`

### Fixed
- Report generation now works after Ctrl+C interruption. Metadata file is written at the start of execution with static fields and updated with dynamic results in a finally block, so partial runs always produce a usable metadata file.
- `ExhaustivePlanner.next_tests(n)` no longer returns aliased `ExecutionInstance` objects when the same matrix entry is picked for different repetitions in the same batch. Each returned test is now a shallow copy with its own `metadata` dict, so `_prepare_execution_artifacts` cannot overwrite an earlier batch entry's `execution_dir` / `repetition` / `script_file`. This prevented duplicate SLURM submissions pointing to the same WorkDir under `benchmark.parallel > 1`.
- Resource and GPU samplers now isolate concurrent SLURM attempts on the same `exec_dir`. Trace files and the sentinel file are now suffixed with the SLURM job id (or the shell PID when running locally), so a requeued second attempt cannot truncate the first attempt's trace or stop its sampler when it exits.
- Per-GPU columns in `__iops_resource_summary.csv` now include the hostname when traces span multiple nodes (`node01_gpu0_*`, `node02_gpu0_*`), so same-indexed GPUs on different hosts no longer overwrite each other. Single-node runs keep the original `gpuN_*` naming.

## [3.5.3] - 2026-03-31

This release introduces GPU monitoring support to the IOPS probe system, enabling
energy consumption tracking, power draw analysis, and thermal monitoring during
benchmark execution. It also adds a new Resource Sampling section to HTML reports
and a JUBE-to-IOPS configuration converter.

### Added
- GPU sampling probe (`probes.gpu_sampling`) for real-time GPU monitoring during benchmark execution
  - Tracks utilization, memory usage, temperature, power draw, and clock speeds
  - Supports NVIDIA GPUs via `nvidia-smi`, with vendor detection designed for future AMD/Intel extension
  - Gracefully skips when no supported GPU is detected (no errors, no empty files)
  - Per-node GPU sample files (`__iops_gpu_trace_<hostname>.csv`) with SLURM multi-node support
  - Energy consumption calculation via trapezoidal integration of power over time (`gpu_energy_j`)
  - Per-GPU metric columns (`gpu0_avg_power_w`, `gpu1_energy_j`, etc.) for multi-GPU analysis
  - Aggregated GPU metrics in `__iops_resource_summary.csv` alongside CPU/memory metrics
  - GPU hardware detection in system snapshot (`gpu_count`, `gpu_model`, `gpu_driver`, `gpu_memory_mib`)
- Resource Sampling section in HTML reports (`reporting.sections.resource_sampling`)
  - Auto-detects available CPU/memory and GPU metrics from `__iops_resource_summary.csv`
  - Summary table with min/max/mean for each resource metric
  - Heatmap and bar chart visualizations correlating user variables with resource footprint
  - Enabled by default when resource summary data is available
- `iops convert` command for translating JUBE XML benchmarks to IOPS YAML format [experimental]
- Jinja2 templating support in `benchmark.cache_file`
- `examples/gpu_stress/` synthetic CUDA SGEMM workload for testing GPU probes

### Fixed
- GPU sampler CSV parsing for GPU names containing spaces (e.g. "Tesla V100-PCIE-16GB")
- GPU aggregate metrics no longer diluted by idle GPUs on multi-GPU machines

## [3.5.2] - 2026-03-02

### Added
- Adaptive variable probing (`search_method: "adaptive"`) for finding threshold values automatically
  - Supports multiplicative (`factor`), additive (`increment`), and custom (`step_expr`) progression
  - Configurable stop conditions via `stop_when` expressions (exit code, metrics, execution time)
  - Independent probes per swept variable combination
  - Probe results stored in `__iops_run_metadata.json` under `adaptive_results`
- `list` variable type for indexed access to correlated parameter arrays
- `--add VAR[:TYPE]=VALUE` option for `iops cache rebuild` to add typed variables to all cache entries
- `machines` section for per-machine config overrides with deep-merge semantics
- `--machine NAME` flag (and `IOPS_MACHINE` env var) for `iops run` and `iops check`
- `iops check --resolve [FILE]` to output the fully merged config as YAML
- `iops generate --machines` to scaffold a config with machine override examples
- `metrics` global variable in parser scripts (list of expected metric names for selective computation)
- Copy input YAML config to run folder for reproducibility
- Reports section on the website with interactive Plotly report viewer

### Changed
- Made scikit-optimize an optional dependency, installed via `pip install iops-benchmark[bayesian]`

### Fixed
- `--resolve` now renders multi-line strings (parser scripts, script templates) with YAML literal block style (`|`) instead of escaped single-line format
- Watch mode progress display for adaptive planner
- Parser script now accepts directory paths
- Bayesian test failures when scikit-optimize is not installed

## [3.5.0] - 2026-02-01

### Added
- Resource tracing for CPU and memory monitoring (`trace_resources`, `trace_interval`)
- Single-allocation mode for batch SLURM execution (`slurm_options.allocation`) [experimental]
- MPI block for automatic MPI launching in single-allocation mode (`scripts[].mpi`)
- `iops cache rebuild` command to exclude variables retroactively
- Parser script context injection (`vars`, `env`, `os_env`, `execution_id`, `repetition` globals)
- `os_env` context variable exposing system environment variables to Jinja2 templates
- `--partial` and `--min-reps` flags for partial archive creation
- Unknown key validation with "did you mean?" suggestions for YAML config
- Core-hours tracking for cache hits in dry-run estimates
- Boolean variables now included in report generation by default (treated as 0/1)
- Plot export to image files (`--export-plots`, `--plot-format`) with pdf, png, svg, jpg, webp support
- Random search evolution section in HTML reports
- NFS auto-detection with lock-free SQLite mode for cache
- Real-time execution status tracking with executor-specific updates
- `early_stop_on_convergence` option for Bayesian optimization to stop when optimizer converges
- `convergence_patience` option to control early stopping sensitivity (default: 3)
- `xi_boost_factor` option to dynamically increase exploration when stuck (default: 5.0)
- `--cache-only` CLI option for cache-only execution (skip tests not in cache)
- Keyboard navigation for watch mode (pause, page scroll, search by test ID)

### Changed
- Renamed `executor_options` to `slurm_options` (old name deprecated, remove in 3.7.0)
- Refactored probe configuration to nested `probes:` section with clearer field names:
  - `collect_system_info` → `probes.system_snapshot`
  - `track_executions` → `probes.execution_index`
  - `trace_resources` → `probes.resource_sampling`
  - `trace_interval` → `probes.sampling_interval`
  (old names deprecated, remove in 3.7.0)
- Renamed `[pdf]` optional dependency to `[plots]` (supports pdf, png, svg, jpg, webp)
- Removed `scripts[].submit` field
- Removed `output.sink.include` option
- Removed Pareto Frontier analysis from reports
- `iops generate` now defaults to SLURM executor (use `--local` for local)
- Separate user labels from IOPS internal metadata in output
- Default output path when `output.sink.path` not specified
- Bayesian optimization now uses MAX/MIN aggregation for repetitions (matching objective) instead of MEAN

### Fixed
- `sections.parallel_coordinates` and `sections.variable_impact` settings being ignored in reports
- Dry-run cache lookup using wrong repetition values
- Constraint evaluation order (swept vars before derived expressions)
- Refactored BayesianPlanner to use pre-built execution matrix (consistent with other planners)
- SQLite cache locking errors on NFS filesystems
- Bayesian optimization nearest-neighbor tie-breaking now deterministic (prefers higher parameter values)

## [3.4.0] - 2026-01-13

### Added
- Subcommand-based CLI structure (`run`, `check`, `generate`, `report`, `find`)
- `find` command to explore execution folders with parameter filtering
- Execution status tracking with `--status` filter (SUCCEEDED, FAILED, ERROR)
- Archive module for workdir portability (`iops archive create/extract`)
- Watch mode for real-time execution monitoring (`iops watch`)
- Conditional variables with `when`/`default` fields
- Enhanced Bayesian optimization with `base_estimator`, `xi`, `kappa`, `n_iterations`
- Search space efficiency statistics in Bayesian reports
- `fallback_to_exhaustive` option for Bayesian planner
- `create_folders_upfront` benchmark option
- System info collection and config validation
- Client-side search for documentation site

### Changed
- YAML file shorthand: `iops config.yaml` works as `iops run config.yaml`
- Renamed `sqlite_db` to `cache_file`
- Renamed `target_metric` to `objective_metric`
- Removed rounds feature and simplified planner architecture
- Made pyarrow an optional dependency
- Portable workdir metadata with relative paths
- Centralized validation logic in loader.py
- Restructured documentation for v3

### Fixed
- Bayesian planner edge case bugs
- Archive progress bar performance with compression level tuning
- Metrics not showing when using `--hide` in watch mode
- Duration tracking to use cached sysinfo
- Search index to include full page content

## [3.2.0] - 2025-12

Major overhaul transforming IOPS into a generic benchmark orchestration framework.

- Generic framework supporting any parametric experiment
- `iops generate` to create configuration templates
- Interactive setup wizard for guided configuration
- Bayesian optimization for intelligent parameter search
- Random sampling planner for parameter space exploration
- Core-hours budget tracking for HPC clusters
- Dry-run mode to preview executions with resource estimates
- HTML report generation with interactive Plotly charts
- Result caching with `--use-cache` flag
- SLURM cluster support with automatic job management
- Parameter constraints to filter invalid configurations
- Configurable SLURM commands via `slurm_options`
- `exhaustive_vars` for hybrid search strategies
- User-configurable reporting system with 8 plot types
- `reporting` configuration section for plot customization
- `--report-config` CLI option to regenerate reports
- Theme configuration (colors, fonts, plotly styles)
- PyPI packaging as `iops-benchmark`
- Spack package support

## [2.0.0] - 2024

Internal development version that introduced architectural changes leading to 3.2.0.

- Database-backed storage for results
- Improved executor architecture with better SLURM support
- Enhanced test coverage and validation
- Refactored planner with greedy strategy and caching

## [1.0.0] - 2023-10-19

Initial release of IOPS as an IOR-specific benchmark orchestration tool.

- IOR benchmark automation with parametric sweeps
- SLURM and local execution support
- Multi-round optimization with binary search heuristics
- HTML report generation with bandwidth graphs
- Configuration via INI files
- Stripe folder management for parallel filesystems
- Test repetitions for statistical validity
- Progress tracking and interruption handling
