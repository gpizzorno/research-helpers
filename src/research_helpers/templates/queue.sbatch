#!/bin/bash
#SBATCH --job-name=queue
#SBATCH --partition=shared
#SBATCH --time=0-08:00
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=4G
#SBATCH --output=logs/queue_%A_%a.out
#SBATCH --error=logs/queue_%A_%a.err
#SBATCH --open-mode=append
#SBATCH --no-requeue
# --no-requeue: when a node stops answering, a requeue can start a second copy
# of an element while the first is still running. Both then append to the same
# part files from two nodes, which on network storage leaves NUL bytes and
# spliced lines that no resume repairs. A failed element is queued again with
# 'queue --pending' instead; 'quarantine' sets aside what a duplicate damaged.

# ---------------------------------------------------------------------------
# Many sweeps through one array: each element runs a block of units, one slice
# of one sweep per line of a queue file, one after another.
#
# All #SBATCH lines must stay together at the top, before any other command:
# SLURM stops parsing them at the first non-comment line.
#
# Write the queue files with 'queue', which prints the exact lines to submit:
#   python -m my_project.sweep queue --run-dir 'runs/campaign/*' \
#       --out queues/campaign --per-task 20
#   sbatch --array=1-37 queue.sbatch queues/campaign.01.units 20
#
# The per-task number is part of the queue: element i runs lines
# (i-1)*K+1 .. i*K, so submitting with a different K than the queue was
# written for runs the wrong blocks. Pass the number 'queue' printed.
#
# Throttle a large array so it does not take a whole partition:
#   sbatch --array=1-1000%200 queue.sbatch queues/campaign.01.units 20
#
# After a partial run, write the unfinished slices to a NEW stem, and only
# once the old array has finished: an element reads its block when it starts,
# so rewriting a file that pending elements will read hands them wrong blocks.
#   python -m my_project.sweep queue --run-dir 'runs/campaign/*' \
#       --out queues/campaign_r1 --per-task 20 --pending
#
# Set SWEEP_NO_RESUME=1 to recompute combinations already recorded.
# ---------------------------------------------------------------------------

set -euo pipefail

UNITS="${1:?usage: sbatch --array=1-N queue.sbatch <queue.units> <per_task>}"
PER_TASK="${2:?usage: sbatch --array=1-N queue.sbatch <queue.units> <per_task>}"

mkdir -p logs

# ===========================================================================
# EDIT THIS BLOCK. Everything above and below is general, this part is your
# cluster and your environment.
# ===========================================================================
# module load python/3.12.5-fasrc01
# source "$(conda info --base)/etc/profile.d/conda.sh"
# conda activate my-env
SWEEP_MODULE="my_project.sweep"     # the module holding your Sweep object
# ===========================================================================

# Call the interpreter by absolute path rather than trusting PATH. Activation
# can "succeed" while leaving PATH wrong: if $CONDA_PREFIX/bin holds no python
# (an interrupted env creation leaves exactly that), 'python' falls through to
# the base install and the job dies later at the first third-party import.
PYTHON="${CONDA_PREFIX:-}/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python)"

if [[ ! -x "$PYTHON" ]]; then
  echo "FATAL: no interpreter found (on $(hostname))." >&2
  echo "  Two potential causes, check them in this order:" >&2
  echo "  1. INHERITED ENVIRONMENT. sbatch --export=ALL copies the submitting" >&2
  echo "     shell's CONDA_* vars into the job, so CONDA_PREFIX can name an" >&2
  echo "     environment this node never activated, and activation then no-ops." >&2
  echo "     Verify by running the same commands interactively:" >&2
  echo "       salloc -p test -t 0-00:10 -c 1 --mem 4G" >&2
  echo "       source \"\$(conda info --base)/etc/profile.d/conda.sh\"" >&2
  echo "       conda activate <env> && ls \"\$CONDA_PREFIX/bin/python\"" >&2
  echo "     If that works the environment is FINE and this is inheritance:" >&2
  echo "     resubmit with --export=NONE, or keep the absolute path above." >&2
  echo "  2. Only if the interactive check ALSO fails is the environment itself" >&2
  echo "     incomplete, and worth rebuilding." >&2
  echo "  diagnose-env.sbatch captures both states and tells them apart." >&2
  exit 1
fi

# Each task owns ONE core, but BLAS defaults to one thread per core on the whole
# node. Without this, dozens of single-core tasks each spawn dozens of threads,
# oversubscribe the node, and the array runs slower than working serially.
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export NUMEXPR_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"

echo "python=$PYTHON"
echo "host=$(hostname) queue=$UNITS element=${SLURM_ARRAY_TASK_ID:-1} per_task=$PER_TASK started=$(date -Is)"

# The element comes from SLURM_ARRAY_TASK_ID. A unit that fails is reported and
# the rest of the block still runs; the element then exits non-zero, which
# sacct shows as FAILED, and 'queue --pending' finds the slice again.
"$PYTHON" -u -m "$SWEEP_MODULE" run-units \
  --units "$UNITS" \
  --per-task "$PER_TASK" \
  ${SWEEP_NO_RESUME:+--no-resume}

echo "finished=$(date -Is)"
