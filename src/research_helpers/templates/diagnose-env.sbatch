#!/bin/bash
#SBATCH --job-name=diagnose-env
#SBATCH --partition=shared
#SBATCH --time=0-00:05
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --output=logs/diagnose_%j.out
#SBATCH --error=logs/diagnose_%j.out

# ---------------------------------------------------------------------------
# Throwaway diagnostic for the most commonest way jobs fail: 'python' resolves to
# the base install inside a batch job but not interactively, so the job fails
# at its first third-party import while the same commands work by hand on a
# login node.
#
# The cause is usually inheritance rather than a broken environment. 'sbatch'
# defaults to --export=ALL, which copies the submitting shell's CONDA_* into
# the job, so CONDA_PREFIX can already name an environment this node never
# activated, and 'conda activate' does nothing. This captures the
# environment before and after activation.
#
#   mkdir -p logs
#   sbatch diagnose-env.sbatch my-env
#   cat logs/diagnose_<jobid>.out
# ---------------------------------------------------------------------------

ENV_NAME="${1:?usage: sbatch diagnose-env.sbatch <conda env name>}"

echo "=== INHERITED from the submitting shell (sbatch defaults to --export=ALL) ==="
echo "SLURM_EXPORT_ENV  = ${SLURM_EXPORT_ENV:-<unset>}"
echo "CONDA_PREFIX      = ${CONDA_PREFIX:-<unset>}   <- if already set, activate may no-op"
echo "CONDA_SHLVL       = ${CONDA_SHLVL:-<unset>}"
echo "CONDA_DEFAULT_ENV = ${CONDA_DEFAULT_ENV:-<unset>}"
echo "which python      = $(command -v python || echo none)"
echo "PATH[1:3]         = $(echo "$PATH" | tr ':' '\n' | head -3 | tr '\n' ' ')"

echo
echo "=== after module load ==="
# EDIT: the module your cluster provides. The suffix changes between installs,
# so check it with 'module avail python' rather than assuming this one.
# module load python/3.12.5-fasrc01
echo "which python      = $(command -v python || echo none)"
echo "which conda       = $(command -v conda || echo none)"

echo
echo "=== after conda.sh + conda activate $ENV_NAME ==="
# Activate through conda.sh rather than 'source activate': the legacy script
# can set CONDA_DEFAULT_ENV and CONDA_PREFIX without prepending the
# environment's bin to PATH.
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"
echo "exit status       = $?"
echo "CONDA_PREFIX      = ${CONDA_PREFIX:-<unset>}"
echo "CONDA_SHLVL       = ${CONDA_SHLVL:-<unset>}"
echo "which python      = $(command -v python || echo none)"
echo "PATH[1:3]         = $(echo "$PATH" | tr ':' '\n' | head -3 | tr '\n' ' ')"

echo
echo "=== does the interpreter actually exist? ==="
ls -la "${CONDA_PREFIX:-/nonexistent}/bin/python" 2>&1

echo
echo "=== does it work when called by absolute path? ==="
"${CONDA_PREFIX:-/nonexistent}/bin/python" -c "import sys; print('  OK', sys.version.split()[0], sys.executable)" 2>&1

echo
echo "=== forcing a clean re-activation ==="
conda deactivate 2>/dev/null
conda activate "$ENV_NAME"
echo "which python      = $(command -v python || echo none)"

echo
echo "=== reading the result ==="
echo "  Absolute path works, 'which python' wrong  -> inheritance. Keep calling the"
echo "    interpreter by absolute path, or resubmit with --export=NONE."
echo "  Absolute path ALSO fails                   -> the environment is genuinely"
echo "    incomplete. Reproduce it interactively before rebuilding:"
echo "      salloc -p test -t 0-00:10 -c 1 --mem 4G"
