---
title: "Using IOPS on Grid'5000"
date: 2026-01-26
tags: ["grid5000", "oar", "slurm", "hpc", "tutorial"]
hidden: false
draft: false
author: "Jerome Charousset, CEA"
---

[Grid'5000](https://www.grid5000.fr/w/Grid5000:Home) is a large-scale and flexible testbed for experiment-driven research in all areas of computer science, with a focus on parallel and distributed computing, including Cloud, HPC, Big Data and AI.

On Grid'5000 platform the reservation of computing nodes and scheduling of batch jobs is managed by the [OAR software suite](https://oar.readthedocs.io/en/2.5/), while IOPS is only supporting [Slurm](https://slurm.schedmd.com/documentation.html) as a batch scheduler.
Thankfully, the high level of similarity between OAR and Slurm (at least from a user perspective) makes it easy to **run IOPS on Grid'5000 front-end with OAR being used to schedule & control the test jobs on the computing nodes**. Let's see how...

*This guide was written by **Jerome Charousset** from CEA.*


## Step 1: install wrappers

The approach consists in creating wrappers that encapsulate calls to the OAR commands and mimic the behaviour of corresponding Slurm commands. 
IOPS will just launch the wrappers and treat their outputs as if they were the usual Slurm commands.

When connected on Grid'5000 front-end, 
1. create the following files somewhere in your home directory, for instance in `$HOME/.local/bin`
- File `sbatch_oar_wrapper`:
~~~bash
#!/usr/bin/env bash

script="$1"

# Make sure the script is executable (IOPS currently does not set the +x)
chmod +x "$script"

# Submit job using OAR with the -S option :
# will can the script file for extra options to apply to the job (lines starting with #OAR)
output=$(oarsub -S "$script")

# Extract job ID from the oarsub output
# Example of output format : "OAR_JOB_ID=1957551"
job_id=$(echo "$output" | awk -F= '/OAR_JOB_ID/ {print $2; exit}')

# Print only the job ID as exepected by IOPS method _parse_jobid in class SlurmExecutor
echo "$job_id"
~~~	

- File `squeue_oar_wrapper`:
	
~~~bash
#!/usr/bin/env bash

job_id="$1"

# Extract current job state from oarstat
state=$(oarstat -s -j "$job_id" | awk -v id="$job_id" '$1 == id":" {print $2; exit}')

# Now convert OAR job state into a Slurm job state
# At this moment IOPS only distinguish between :
#    RUNNING, PENDING and "no state" (condition for stopping the pooling loop)
# Nevertheless we try to map more states to help debugging
case "$state" in
  "" |Terminated | Error) ret="" ;;
  Waiting | toLaunch | Launching | toAckReservation) ret="PENDING" ;;
  Running) ret="RUNNING" ;;
  Finishing) ret="COMPLETING" ;;
  Suspended) ret="SUSPENDED" ;;
  Hold) ret= "CANCELLED" ;;
  *) ret="UNKNOWN" ;;
esac

echo "$ret"
~~~
-  File `scontrol_oar_wrapper`:
~~~bash
#!/usr/bin/env bash

job_id="$1"

# Query OAR in full JSON mode
job_json=$(oarstat -J -j "$job_id" 2>/dev/null)

# Default values
state=""
exitcode=""

# If job exists, parse state
if [[ -n "$job_json" ]]; then
    # Use jq to extract state and exit code if available
    state=$(echo "$job_json" | jq -r --arg id "$job_id" '.[$id].state')
    exitcode=$(echo "$job_json" | jq -r --arg id "$job_id" '.[$id].exit_code')
fi

# Map OAR states (as described in https://oar.readthedocs.io/en/2.5/admin/database-scheme.html#jobs)
# to Slurm-like job states. At this moment anything different than "COMPLETED" will be
# interpreted as a failure
case "$state" in
  Waiting | toLaunch | Launching | toAckReservation) jobstate="PENDING" ;;
  Hold) jobstate="CANCELLED" ;;
  Running) jobstate="RUNNING" ;;
  Error | toError) jobstate="FAILED" ;;
  Suspended) jobstate="SUSPENDED" ;;
  Finishing) jobstate="COMPLETING" ;;   
  # Or you might map this to "COMPLETED" if you want to ignore jobs remaining in "finishing" state- cf:
  # https://oar.readthedocs.io/en/2.5/admin/faq.html#a-job-remains-in-the-finishing-state-what-can-i-do)
  Terminated)jobstate="COMPLETED" ;;
  *) jobstate="UNKNOWN" ;;
esac

# Print in the exact format expected by IOPS method _scontrol_info in class SlurmExecutor
# Expected format for exit code is <exit>:<sig> ; we just set sig to 0 as OAR does not provide this info
echo "JobState=$jobstate ExitCode=$exitcode:0"
~~~
2. make sure the chosen directory is added in your `$PATH` automatically for each new session, for instance by adding the following line to your `$HOME/.profile` and/or `$HOME/.bashrc`:
~~~bash
export PATH=$HOME/.local/bin:$PATH
~~~

> [!important]
> Please remember you have a different home directory on each Grid'5000 site, so the above instructions must be repeated on each of the sites expected to run IOPS.


## Step 2: configure IOPS to call the wrappers

In the YAML configuration file of your benchmark, you shall instruct IOPS to use Slurm executor, but to call the wrappers instead of the standard Slurm commands. This is achieved by setting the `executor` and `executor_options` properties:
~~~yaml
benchmark:
  name: "My Benchmark"
  workdir: "./"
  repetitions: 3
  search_method: "exhaustive"
  
  executor: "slurm"
  executor_options:                 # Needed for OAR: executor-specific configuration
    commands:                       #   SLURM command templates
      submit: "sbatch_oar_wrapper"              #  Submit command
      status: "squeue_oar_wrapper {job_id}" 	#  Status template
      info: "scontrol_oar_wrapper {job_id}"     #  Info template 
      cancel: "oardel {job_id}"                	#  Cancel template 
~~~

Please note that we did not create a wrapper for job cancellation, as IOPS can directly call the OAR-native `oardel` command, there is no need for any transformation or conversion.

## Step 3: adapt your scripts

As all the scripts defined in the YAML configuration file of your benchmark will ultimately be launched by OAR instead of Slurm, they must contain directives that can be understood by OAR. Any Slurm directive (`#SBATCH` directives) will be silently ignored. 

See subsection "Batch job using OAR scripts" in [Grid'5000 Getting Started](https://www.grid5000.fr/w/Getting_Started#Reserving_resources_with_OAR:_the_basics) for an introduction to OAR directives.

In the following example, we ask for a reservation of multiple nodes (according to the actual value of the `nodes` variable) during 1 hour maximum and capture the standard output and standard error in files called `stdout` and `stderr`:

~~~yaml
scripts:
  - name: "my_script"
    submit: ""
    script_template: |
      #!/bin/bash
      #OAR -l nodes={{ nodes }},walltime=1:00:00
      #OAR -O stdout
      #OAR -E stderr

      set -euo pipefail
      mpirun -machinefile $OAR_NODEFILE {{ command.template }}

    parser:
	...
~~~


Et voilà !