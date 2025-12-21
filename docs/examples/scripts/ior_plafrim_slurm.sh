#!/bin/bash

#SBATCH --job-name=iops_{{ execution_id }}
#SBATCH --ntasks={{ ntasks }}
#SBATCH --nodes={{ nodes }}
#SBATCH --ntasks-per-node={{ processes_per_node }}
#SBATCH --time=04:00:00
#SBATCH --chdir={{ execution_dir }}
#SBATCH -o batch%j.out
#SBATCH -e batch%j.err
#SBATCH --exclusive 
#SBATCH --constraint ['bora']

module purge
module load mpi/openmpi/4.0.1

# Log what SLURM actually allocated (for debugging)
echo "=== SLURM Allocation Info ==="
echo "Requested nodes: {{ nodes }}"
echo "Requested ntasks-per-node: {{ processes_per_node }}"
echo "Allocated SLURM_JOB_NUM_NODES: $SLURM_JOB_NUM_NODES"
echo "Allocated SLURM_NNODES: $SLURM_NNODES"
echo "Allocated SLURM_NODELIST: $SLURM_NODELIST"
echo "Allocated SLURM_NTASKS: $SLURM_NTASKS"
echo "Allocated SLURM_TASKS_PER_NODE: $SLURM_TASKS_PER_NODE"
echo "============================="

# Execute the command (SLURM sets task count automatically)
mpirun  --mca btl ^uct --mca fs ^lustre --mca osc ^ucx --mca pml ^ucx --mca btl_openib_allow_ib 1 \
{{ command.template }}
