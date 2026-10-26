#!/usr/bin/env bash
# Remove stale branches from GitHub, keeping every commit reachable.
#
#   bash scripts/cleanup-branches.sh           # show what would happen (nothing is changed)
#   bash scripts/cleanup-branches.sh --apply   # do it
#
# Kept: main and every branch with an open pull request.
# A branch fully contained in main (git merge-base --is-ancestor) is deleted.
# Any other branch (squash-merged or abandoned) first gets the tag archive/<branch> at its tip,
# then is deleted: `git checkout -b <branch> archive/<branch>` restores it.
# Needs git push rights to origin and the GitHub CLI (gh) signed in to read open pull requests.
set -euo pipefail

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1
REMOTE="${REMOTE:-origin}"
REPO="${REPO:-$(git remote get-url "$REMOTE" | sed -E 's#(\.git)?$##; s#^.*github\.com[:/]##')}"

git fetch --quiet --prune "$REMOTE" '+refs/heads/*:refs/remotes/'"$REMOTE"'/*' '+refs/tags/*:refs/tags/*'
mapfile -t open_heads < <(gh api "repos/$REPO/pulls?state=open&per_page=100" --paginate --jq '.[].head.ref')

deleted=0 archived=0 kept=0
while read -r ref sha; do
  branch="${ref#refs/remotes/$REMOTE/}"
  [ "$branch" = "HEAD" ] && continue
  if [ "$branch" = "main" ] || printf '%s\n' "${open_heads[@]}" | grep -qxF "$branch"; then
    echo "keep     $branch"
    kept=$((kept + 1))
    continue
  fi
  if git merge-base --is-ancestor "$sha" "$REMOTE/main"; then
    echo "delete   $branch (contained in main)"
  else
    echo "archive  $branch -> tag archive/$branch, then delete"
    if [ "$APPLY" = 1 ]; then
      git push --quiet "$REMOTE" "$sha:refs/tags/archive/$branch"
    fi
    archived=$((archived + 1))
  fi
  if [ "$APPLY" = 1 ]; then
    git push --quiet "$REMOTE" --delete "$branch"
  fi
  deleted=$((deleted + 1))
done < <(git for-each-ref --format='%(refname) %(objectname)' "refs/remotes/$REMOTE")

if [ "$APPLY" = 1 ]; then
  echo "done: $deleted branches deleted ($archived archived as tags), $kept kept"
else
  echo "dry run: $deleted branches would be deleted ($archived archived as tags first), $kept kept; rerun with --apply"
fi
