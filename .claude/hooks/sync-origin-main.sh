#!/usr/bin/env bash
# Hook SessionStart : aligne la branche courante sur origin/main avant de
# commencer une tâche. Fast-forward uniquement, et seulement si la branche n'a
# aucun commit propre et aucun fichier suivi modifié — sinon on se contente de
# signaler le retard. La sortie est ajoutée au contexte de la session.

# Tout dans une fonction : le merge peut réécrire ce fichier pendant qu'il tourne.
main() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

  if ! git fetch --quiet origin main 2>/dev/null; then
    echo "sync origin/main : fetch impossible, branche laissée telle quelle."
    return 0
  fi

  local ahead behind
  ahead=$(git rev-list --count origin/main..HEAD)
  behind=$(git rev-list --count HEAD..origin/main)
  [ "$behind" -eq 0 ] && return 0

  if [ "$ahead" -eq 0 ] && [ -z "$(git status --porcelain --untracked-files=no)" ]; then
    if git merge --quiet --ff-only origin/main; then
      echo "sync origin/main : branche avancée de $behind commit(s), HEAD = $(git rev-parse --short HEAD)."
      return 0
    fi
  fi

  echo "sync origin/main : origin/main a $behind commit(s) d'avance, branche non mise à jour ($ahead commit(s) propres ou fichiers modifiés)."
}

main "$@"
