# Nested search: smallest working block size per problem size

This example covers a case IOPS does not support directly:

```
for problem_size in 1000, 2000, 4000, ... :      # outer loop
    for block_size in 16, 32, 64, 128, 256 :     # inner loop
        run it
        if it WORKED: stop trying block sizes, move to the next problem_size
```

Both loops decide when to stop based on the return code, but IOPS allows only
**one** variable driven by results. A config with two `adaptive` variables is
rejected:

```
Only one adaptive variable is supported per config, but found 2: ['problem_size', 'block_size']
```

## The approach

Only the inner loop really needs the return code. The outer loop is just a list
of problem sizes to walk through. So the outer variable becomes an ordinary
sweep, and the single adaptive slot is spent on the inner one. IOPS then runs
one independent block size search per problem size, which is the nesting we
wanted.

Two things make the inner loop behave like a list with early exit:

1. **`step_expr` indexes a list.** Adaptive variables usually double or add a
   constant, but the step rule is any Jinja2 expression.
   `[16, 32, 64, 128, 256][iteration]` makes the variable walk exactly those
   values, in order.

2. **`stop_when` is inverted.** The usual `exit_code != 0` means "keep going
   while it works". Here `exit_code == 0` means "keep going while it fails,
   stop at the first block size that succeeds".

## What `iteration` is

`iteration` is not a variable you declare. It is a counter supplied by IOPS,
available inside the `adaptive:` block only, alongside `previous` (the value
just tested).

The first value does **not** come from `step_expr`. It comes from `initial`.
`step_expr` is only asked for the *next* value, after a run has finished:

| What happens          | `iteration` | Value used | Came from             |
|-----------------------|-------------|------------|-----------------------|
| First run             | 0           | 16         | `initial`             |
| Failed, need next     | 1           | 32         | `step_expr` → `[1]`   |
| Failed, need next     | 2           | 64         | `step_expr` → `[2]`   |
| Failed, need next     | 3           | 128        | `step_expr` → `[3]`   |
| Failed, need next     | 4           | 256        | `step_expr` → `[4]`   |

So the list lines up because by the time the expression is first evaluated,
`iteration` has already ticked to 1. Element 0 of the list is never read;
`initial` supplies that value instead, which is why the two must agree.

## Two rules to respect

**`max_iterations` must equal the number of values in the list.** If it is
larger, the search eventually asks for an element past the end of the list.
`iops check` catches this before anything runs:

```
var 'block_size' adaptive: 'step_expr' fails at iteration 5, before
'max_iterations' (6) is reached: list object has no element 5
  'step_expr' indexes a list with fewer than 6 values. Set 'max_iterations'
  to the number of values in the list, or add values to the list.
```

Adding a block size to the list means bumping `max_iterations` as well. Run
`iops check <config>.yaml` after editing either one.

If you leave `max_iterations` out entirely, the probe is unbounded and IOPS
cannot check the list length up front. In that case a probe that runs out of
values ends with `stop_reason=step_error` and the rest of the run carries on.

**Keep `repetitions: 1`.** With more, any single repetition that meets
`stop_when` ends the probe for that value.

## Reading the results

The end-of-run summary prints the block size that **worked** under the label
`failed`:

```
Adaptive probing results for 'block_size':
  problem_size=1000: found=None, failed=16,  iterations=1, stop_reason=condition_met
  problem_size=2000: found=16,   failed=32,  iterations=2, stop_reason=condition_met
  problem_size=4000: found=32,   failed=64,  iterations=3, stop_reason=condition_met
  problem_size=8000: found=64,   failed=128, iterations=4, stop_reason=condition_met
```

For `problem_size=8000`, the block size that succeeded is **128**. The numbers
are right, the labels read backwards, because IOPS names them after the normal
convention where stopping means something went wrong. The per-run `returncode`
is also written to `results.csv` if you prefer reading it from there.

Note the run counts: 1, 2, 3 and 4 instead of 5 every time. That is the early
exit doing its job, 10 runs in total rather than 20.

## Trying it

`my_benchmark` is a stub that succeeds only when `block_size * 100 >=
problem_size`, so you can see the search work without a real code. IOPS runs
each test from its own execution directory, so point the command at an absolute
path:

```bash
mkdir -p workdir
sed "s|\./my_benchmark|$PWD/my_benchmark|" nested_block_size.yaml > /tmp/demo.yaml
iops run /tmp/demo.yaml
```

For real use, replace the `command.template` in `nested_block_size.yaml` with
your own benchmark and adjust the two lists.

## If you want the outer loop to grow automatically

This example enumerates the problem sizes upfront. If a problem size is too
large for every block size, that row runs all 5 block sizes and reports
`stop_reason=max_iterations`.

To have the outer limit discovered instead, flip the nesting: sweep
`block_size` as a normal list and make `problem_size` adaptive with
`stop_when: "exit_code != 0"`. That reports the maximum problem size per block
size and terminates on its own, but it loses the early exit (20 runs instead of
10 in the demo above).
