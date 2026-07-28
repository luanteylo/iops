# Staircase search: block count needed per problem size

Two variables that have to move together, one growing while the benchmark
works and the other stepping up whenever it stops:

```
for problem_size in 1000, 2000, 3000, ... :
    if it works with the current number_of_blocks: go to the next problem_size
    if it fails:                                   use more blocks, retry the same size
    if there are no larger block counts left:      stop
```

An adaptive variable alone cannot do this, because it finishes the first time
`stop_when` triggers. Pairing it with an **escalating** variable changes what
happens at that moment: the escalating variable advances and the same adaptive
value is retested, and the probe ends only when the escalation values run out.

## The config

```yaml
problem_size:
  type: int
  adaptive:                       # workload axis
    initial: 1000
    increment: 1000
    stop_when: "exit_code != 0"
    max_iterations: 20

number_of_blocks:
  type: int
  escalate:                       # resource axis
    values: [1, 4, 16]
```

There is only one condition to reason about. Escalation is driven by the
adaptive variable's own `stop_when`, so whatever makes the probe stop is what
makes the resource step up.

## What it runs

Against `my_benchmark`, where each problem size needs four times the blocks of
the one before:

| Run | Result | Action |
|-----|--------|--------|
| `(1000, 1)` | works | advance problem_size |
| `(2000, 1)` | fails | escalate, retry 2000 |
| `(2000, 4)` | works | advance problem_size |
| `(3000, 4)` | fails | escalate, retry 3000 |
| `(3000, 16)` | works | advance problem_size |
| `(4000, 16)` | fails | escalation exhausted, stop |

Six runs. Sweeping `number_of_blocks` instead would restart from 1 for every
problem size and take nine, and the gap widens with longer lists: a staircase
costs `P + B - 1` runs where a sweep costs up to `P x B`.

## Reading the results

```
Adaptive probing results for 'problem_size' (escalating 'number_of_blocks'):
  (no swept vars):
    number_of_blocks=1: reached problem_size=1000
    number_of_blocks=4: reached problem_size=2000
    number_of_blocks=16: reached problem_size=3000
    stop_reason=escalation_exhausted, stopped at problem_size=4000
```

The frontier reads along either axis: the smallest block count each problem
size needs, or the largest problem size each block count can handle. Same three
rows.

It is also in `__iops_run_metadata.json` under `adaptive_results`, as a
`frontier` list. A block count that never succeeded reports `null` rather than
inheriting the previous level's value, so a level is never credited with a run
that did not happen.

## The assumption to check first

The staircase never goes back down. It assumes a block count that fails at one
problem size also fails at every larger one, which is what makes it safe to
carry the resource level forward instead of rechecking smaller ones.

That holds for capacity limits, where more of the resource never hurts. It does
**not** hold if large block counts can fail on their own, say through
communication overhead. In that case the search will walk past working
configurations. Sweep `number_of_blocks` normally instead, so every combination
is tested.

## Trying it

`my_benchmark` is a stub, so you can watch the search work without a real code.
IOPS runs each test from its own execution directory, so point the command at
an absolute path:

```bash
mkdir -p workdir
sed "s|\./my_benchmark|$PWD/my_benchmark|" blocks_per_problem_size.yaml > /tmp/demo.yaml
iops run /tmp/demo.yaml
```

For real use, replace `command.template` with your own benchmark and adjust the
two axes.
