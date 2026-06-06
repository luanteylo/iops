# Image Gallery + Version Capture Example

This example demonstrates two IOPS reporting features:

1. **Per-test image gallery** (`reporting.gallery`): each execution renders a small
   synthetic field image, and the HTML report embeds them as a thumbnail grid (click a
   thumbnail to enlarge). This mirrors the real use case of capturing a simulation's
   final-state thumbnail as a visual sanity check before trusting the metrics.
2. **Software version capture** (`benchmark.probes.versions`): the versions of `python`,
   `numpy` and `matplotlib` are recorded once per execution and shown in a table. If a
   component's version differs across executions, the report shows a drift warning (the
   cache-mixing detector).

## Prerequisites

- `numpy` and `matplotlib` (the script uses them to generate the example images):
  ```bash
  pip install numpy matplotlib
  ```
- `Pillow` is optional; it enables `reporting.gallery.max_width` downscaling.

## Run

```bash
mkdir -p workdir_gallery
iops run examples/gallery_and_versions/gallery_and_versions.yaml
```

Then open `workdir_gallery/run_001/analysis_report.html` and scroll to:

- **Software Versions** (near the top): the per-execution version table.
- **Field thumbnails** (near the bottom): the image gallery.

## Key points

### The `{{ artifacts_dir }}` built-in

The script writes images with:

```bash
mkdir -p {{ artifacts_dir }}
... savefig {{ artifacts_dir }}/final_state.png
```

`{{ artifacts_dir }}` resolves to `<execution_dir>/<reporting.gallery.folder>` (default
`<execution_dir>/images`). Using it means the script never hardcodes the folder name, so
it always matches whatever `reporting.gallery.folder` is set to.

### Convention folder vs. explicit sources

This example uses the **convention folder**: any file matching `pattern` inside the
gallery `folder` is auto-discovered. You can also point at images explicitly with
`reporting.gallery.sources` (a list of Jinja2-templated paths resolved per execution),
and the two can be combined.

### Seeing the drift warning

Versions are identical across executions here, so no warning appears. To see the
cache-mixing detector in action, edit one execution's `__iops_versions.json` to a
different value and regenerate the report:

```bash
iops report workdir_gallery/run_001
```
