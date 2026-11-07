#!/usr/bin/env bash
# v28.90.0 (stage 20, N9): how changes reach main — a branch, a commit of the named files, a pull request.
# Never pushes to main (it is protected; every change goes through the full CI and a squash merge) and never adds
# everything with «git add .» (a local .env or key would leave the machine). Usage:
#   scripts/open-pr.sh <branch> "<title>" <file>...
set -euo pipefail
[ $# -ge 3 ] || { echo "usage: $0 <branch> \"<title>\" <file>..."; exit 2; }
branch="$1"; title="$2"; shift 2
case "$branch" in main|master|"") echo "refusing to commit to $branch: open a branch for the change"; exit 2 ;; esac
command -v gh >/dev/null || { echo "GitHub CLI (gh) is needed: https://cli.github.com"; exit 2; }
for f in "$@"; do
  case "$f" in *.env|*.env.*|*.pem|*.key|*.p8|*.jks|*.keystore|*secret*) echo "refusing to commit $f: it looks like a secret"; exit 2 ;; esac
done
git fetch -q origin main
if git show-ref -q --verify "refs/heads/$branch"; then git switch -q "$branch"; else git switch -q -c "$branch" origin/main; fi
git add -- "$@"
git diff --cached --quiet && { echo "nothing to commit in: $*"; exit 1; }
git commit -q -m "$title"
git push -q -u origin "$branch"
gh pr create --base main --head "$branch" --title "$title" --body-file .github/PULL_REQUEST_TEMPLATE.md
echo "Pull request opened: it merges after the whole CI is green (squash)."
