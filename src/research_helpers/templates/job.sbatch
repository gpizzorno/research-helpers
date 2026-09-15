#!/bin/bash
#SBATCH --job-name=job
#SBATCH --partition=shared
#SBATCH --time=0-08:00
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=8G
#SBATCH --output=logs/job_%j.out
#SBATCH --error=logs/job_%j.err
#SBATCH --open-mode=append

# ---------------------------------------------------------------------------
# Run one script as a single job.
#
# 'sweep.sbatch' runs a planned grid as an array, this runs everything else.
#
# All #SBATCH lines must stay together at the top, before any other command:
# SLURM stops parsing them at the first non-comment line.
#
# Submit, passing the script and its arguments:
#   sbatch job.sbatch scripts/evaluate.py --preset full --out runs/full.json
#
# Override resources at submit time without editing this file:
#   sbatch -t 0-12:00 --mem-per-cpu=32G job.sbatch scripts/evaluate.py --out runs/full.json
#
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT="${1:?usage: sbatch job.sbatch <script.py> [args...]}"
shift

mkdir -p logs

# ===========================================================================
# EDIT THIS BLOCK. Everything above and below is general, this part is cluster
# and environment specific.
# ===========================================================================
# module load python/3.12.5-fasrc01
# source "$(conda info --base)/etc/profile.d/conda.sh"
# conda activate my-env
# ===========================================================================

# Call the interpreter by absolute path rather than trusting PATH. Activation
# can "succeed" while leaving PATH wrong.
PYTHON="${CONDA_PREFIX:-}/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python)"

if [[ ! -x "$PYTHON" ]]; then
  echo "FATAL: no interpreter found (on $(hostname))." >&2
  echo "  See diagnose-env.sbatch, which captures the environment before and" >&2
  echo "  after activation." >&2
  exit 1
fi

# Check the environment here rather than letting the script fail at its first
# import.
#
#   if ! "$PYTHON" -c "import my_package" 2>/dev/null; then
#     echo "FATAL: the environment is incomplete on $(hostname)." >&2
#     echo "  interpreter: $PYTHON" >&2
#     echo "  Run 'pip install -e .' from the project root with the env active." >&2
#     exit 1
#   fi
#

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export NUMEXPR_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"

echo "python=$PYTHON"
echo "script=$SCRIPT args=$*"
echo "host=$(hostname) job=${SLURM_JOB_ID:-none} started=$(date -Is)"

# -u so the log fills as the script runs.
"$PYTHON" -u "$SCRIPT" "$@"

echo "finished=$(date -Is)"
