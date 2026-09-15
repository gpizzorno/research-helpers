#!/bin/bash
#SBATCH --job-name=sweep
#SBATCH --partition=shared
#SBATCH --time=0-04:00
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=8G
#SBATCH --output=logs/sweep_%A_%a.out
#SBATCH --error=logs/sweep_%A_%a.err
#SBATCH --open-mode=append

# ---------------------------------------------------------------------------
# One array task per slice of a parameter grid.
#
# All #SBATCH lines must stay together at the top, before any other command:
# SLURM stops parsing them at the first non-comment line.
#
# Submit with the array range that 'plan' printed:
#   sbatch --array=1-500 sweep.sbatch runs/my-sweep
#
# Override resources at submit time without editing this file:
#   sbatch --array=1-500 -t 0-08:00 --mem-per-cpu=16G sweep.sbatch runs/my-sweep
#
# Re-run only the tasks that failed. Slices stay identical to the original
# submission, because the slice width comes from the manifest and not from the
# size of this array:
#   sbatch --array=17,42,103-107 sweep.sbatch runs/my-sweep
#
# 'status' prints that range, already collapsed into --array syntax:
#   python -m my_project.sweep status --run-dir runs/my-sweep
#
# --open-mode=append keeps logs across a requeue.
# ---------------------------------------------------------------------------

set -euo pipefail

RUN_DIR="${1:?usage: sbatch --array=1-N sweep.sbatch <run_dir>}"

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
echo "host=$(hostname) task=${SLURM_ARRAY_TASK_ID:-1} started=$(date -Is)"

# The task index comes from SLURM_ARRAY_TASK_ID, and the slice width from the
# MANIFEST—not from SLURM_ARRAY_TASK_COUNT. That is what makes a sparse
# resubmission work: '--array=17,42' have a task count of 2, and slicing by that
# would cut the whole grid in two rather than reproduce slices 17 and 42.
# Set SWEEP_TASKS only to deliberately re-partition.
"$PYTHON" -u -m "$SWEEP_MODULE" run \
  --run-dir "$RUN_DIR" \
  ${SWEEP_TASKS:+--tasks "$SWEEP_TASKS"}

echo "finished=$(date -Is)"
