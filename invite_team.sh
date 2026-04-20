#!/usr/bin/env bash
# invite_team.sh — Add CommPlex collaborators to GitHub repos
# Run from a terminal with `gh` CLI authenticated (available in Codespaces)
#
# Usage:
#   bash invite_team.sh                          # invites to monorepo only
#   bash invite_team.sh --all-repos              # invites to all 5 repos
#   bash invite_team.sh --username charles_gh_handle --role write
#
# NOTE: Requires GitHub usernames, not email addresses.
#       Charles, Cynthia, and Justin need to create GitHub accounts first
#       and share their @username with Kenyon.
#
# Emails on file (for reference):
#   Charles: ccp@shy2shy.com
#   Cynthia: thia@shy2shy.com
#   Justin:  jstnshw@shy2shy.com

set -euo pipefail

OWNER="KenyukiShy"

REPOS=(
  "Arc-Badlands-CommPlex"
)

ALL_REPOS=(
  "Arc-Badlands-CommPlex"
  "CommPlexSpec"
  "CommPlexCore"
  "CommPlexAPI"
  "CommPlexEdge"
)

# ── Known usernames (fill in when they share them) ────────────────────────────
CHARLES_GH=""    # fill in: e.g. "charlesperrine"
CYNTHIA_GH=""    # fill in: e.g. "cynthia-ennis"
JUSTIN_GH=""     # fill in: e.g. "jstnshw"

declare -A TEAM_ROLES
TEAM_ROLES["$CHARLES_GH"]="write"
TEAM_ROLES["$CYNTHIA_GH"]="write"
TEAM_ROLES["$JUSTIN_GH"]="write"

invite_user() {
  local REPO="$1" USERNAME="$2" ROLE="$3"
  [[ -z "$USERNAME" ]] && { echo "  → skipping (no username set for this member)"; return; }
  echo -n "  Inviting @${USERNAME} to ${OWNER}/${REPO} (${ROLE})... "
  if gh api -X PUT "repos/${OWNER}/${REPO}/collaborators/${USERNAME}" -f permission="${ROLE}" &>/dev/null; then
    echo "✓"
  else
    echo "FAILED (check username and gh auth)"
  fi
}

# ── Parse args ────────────────────────────────────────────────────────────────
USE_ALL=false
SINGLE_USER=""; SINGLE_ROLE="write"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all-repos)         USE_ALL=true ;;
    --username)          SINGLE_USER="$2"; shift ;;
    --role)              SINGLE_ROLE="$2"; shift ;;
    *) ;;
  esac
  shift
done

[[ "$USE_ALL" == "true" ]] && REPOS=("${ALL_REPOS[@]}")

# ── Check gh auth ─────────────────────────────────────────────────────────────
if ! gh auth status &>/dev/null; then
  echo "❌ gh CLI not authenticated."
  echo "   Run: gh auth login"
  exit 1
fi

echo "CommPlex Team Invites"
echo "Owner: ${OWNER}"
echo "Repos: ${REPOS[*]}"
echo ""

for REPO in "${REPOS[@]}"; do
  echo "── ${REPO} ──"
  if [[ -n "$SINGLE_USER" ]]; then
    invite_user "$REPO" "$SINGLE_USER" "$SINGLE_ROLE"
  else
    for USERNAME in "${!TEAM_ROLES[@]}"; do
      ROLE="${TEAM_ROLES[$USERNAME]}"
      echo -n "  @${USERNAME:-<not set>}: "
      invite_user "$REPO" "$USERNAME" "$ROLE"
    done
  fi
  echo ""
done

echo ""
echo "Done. Invited collaborators will receive an email from GitHub."
echo ""
echo "To fill in usernames, edit this script:"
echo "  CHARLES_GH=\"their_github_username\""
echo "  CYNTHIA_GH=\"their_github_username\""
echo "  JUSTIN_GH=\"their_github_username\""
echo ""
echo "Or add one at a time:"
echo "  bash invite_team.sh --username their_handle --role write"
