#!/usr/bin/env bash
# Pre-push guard for the public repo. Blocks private paths, DB/subtitle/transcript files,
# files over 1 MB, and denylisted terms (list lives in the private repo). Fails closed.
# Install: cp scripts/public-guard.sh .git/hooks/pre-push
# Without hook stdin (manual run) it scans everything reachable from HEAD.
set -u
ROOT="$(git rev-parse --show-toplevel)"
PRIVATE_DIR="${PRIVATE_DIR:-$ROOT/../cold-hard-truth-bro-private}"
DENY="$PRIVATE_DIR/guard-denylist.txt"
fail=0
bad() { echo "public-guard: BLOCKED: $*" >&2; fail=1; }

[ -f "$DENY" ] || { echo "public-guard: BLOCKED: denylist not found at $DENY (fail closed)" >&2; exit 1; }
TERMS="$(mktemp)"; trap 'rm -f "$TERMS"' EXIT
grep -v '^[[:space:]]*\(#\|$\)' "$DENY" > "$TERMS"
[ -s "$TERMS" ] || { echo "public-guard: BLOCKED: denylist is empty (fail closed)" >&2; exit 1; }

# Collect commit ranges to inspect
ranges=()
REFS="$(mktemp)"
if [ ! -t 0 ] && read -r first; then
  { echo "$first"; cat; } > "$REFS"
  while read -r lref lsha rref rsha; do
    [ "$lsha" = "0000000000000000000000000000000000000000" ] && continue
    if [ "$rsha" = "0000000000000000000000000000000000000000" ]; then ranges+=("$lsha"); else ranges+=("$rsha..$lsha"); fi
  done < "$REFS"
  rm -f "$REFS"
fi
[ ${#ranges[@]} -eq 0 ] && ranges=("HEAD")

for r in "${ranges[@]}"; do
  # every path touched by the pushed commits, plus the current tree
  paths="$( { git log --name-only --pretty=format: "$r" 2>/dev/null; git ls-files; } | sort -u | sed '/^$/d')"
  while IFS= read -r p; do
    case "$p" in
      prompts/*|kb/*|data/*|evals/private/*|tracker/*) bad "private path: $p";;
      *.db|*.vtt|*.sqlite) bad "forbidden file type: $p";;
      */transcripts/*.json|transcripts/*.json) bad "transcript JSON: $p";;
    esac
  done <<< "$paths"
  # big blobs added in the range
  while read -r sha size path; do
    [ "$size" -gt 1048576 ] 2>/dev/null && bad "file over 1 MB: $path"
  done < <(git rev-list --objects "$r" 2>/dev/null | git cat-file --batch-check='%(objectname) %(objectsize) %(rest)' | awk '$2>1048576')
  # denylisted terms in content, commit messages and author metadata
  if git log -p --format='%an %ae %cn %ce%n%B' "$r" 2>/dev/null | grep -a -i -F -f "$TERMS" -q; then
    hit="$(git log -p --format='%an %ae %cn %ce%n%B' "$r" | grep -a -i -F -f "$TERMS" | head -3 | cut -c1-80)"
    bad "denylisted term in history ($r), e.g.: $hit"
  fi
done
if git ls-files -z | xargs -0 grep -a -i -F -f "$TERMS" -l 2>/dev/null | grep -q .; then
  bad "denylisted term in tracked files: $(git ls-files -z | xargs -0 grep -a -i -F -f "$TERMS" -l | tr '\n' ' ')"
fi
[ $fail -eq 0 ] && echo "public-guard: ok" || { echo "public-guard: push refused" >&2; exit 1; }
