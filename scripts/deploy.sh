#!/usr/bin/env bash
# Deploys main to the real stack: fast-forwards this checkout to origin/main, then `make up`.
# Driven by hand or by the "Déployer main en production" button of the previews page
# (scripts/previews.py).
# Refuses a checkout that is not on main or has modified tracked files: `make up` builds this
# directory, so it would ship (or the merge would clobber) someone's uncommitted work.
# One deploy at a time: it runs under the file lock of scripts/deploy_lock.py, shared with the
# button, and exits 75 when another deploy holds it.
# Spec: docs/spec/04-configuration-et-deploiement.md, section "Deploiement de main".
set -euo pipefail

# Everything runs from a function called on the last line: the merge below may rewrite this
# very file, and bash reads a script as it executes it.
deploy() {
  local self
  self="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  cd "$(dirname "$self")/.."
  if [ -z "${DEPLOY_LOCK_HELD:-}" ]; then
    DEPLOY_LOCK_HELD=1 exec python3 scripts/deploy_lock.py "$self" "$@"
  fi
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$branch" != "main" ]; then
    echo "deploy.sh: le dépôt est sur '$branch', pas sur main : rien n'est déployé" >&2
    exit 1
  fi
  if ! git diff --quiet HEAD --; then
    echo "deploy.sh: des fichiers suivis sont modifiés : rien n'est déployé" >&2
    git status --short --untracked-files=no >&2
    exit 1
  fi
  git fetch -q origin main
  if ! git merge -q --ff-only origin/main; then
    echo "deploy.sh: main a divergé d'origin/main : rien n'est déployé" >&2
    exit 1
  fi
  echo "déploiement de main, commit $(git rev-parse --short HEAD)..."
  make up
}

deploy "$@"
