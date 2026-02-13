"""
FeedFwd — Stop Hook: Feedback Collector
========================================
Runs automatically when a Claude Code session ends.

What it does:
  1. Reads _session_log.json to see which cards were injected
  2. Gets the git diff since session start (what code was written)
  3. For each injected card, checks if its keywords appear in the diff
  4. Cards whose keywords appear → implicit "applied" signal (+0.10)
  5. Cards with no keyword matches → implicit "ignored" signal (-0.02)
  6. Outputs a summary and clears the session log

How implicit feedback works:
  At session start, inject.py records the git HEAD SHA. At session end,
  we diff from that SHA to the current state (committed + uncommitted).
  If keywords from an injected card appear in the diff, it means the
  technique was likely applied during the session.

  Example: Card "uv-inline-dependencies" has keywords ["uv", "script",
  "inline dependencies"]. If the git diff shows a new file with a
  "# /// script" comment → keywords matched → +0.10.

Score change reference:
  +0.15  Explicit "useful" feedback (future: /feedback command)
  +0.10  Implicit "applied" (keywords found in git diff) ← this hook
  -0.02  Implicit "ignored" (injected, no keywords in diff) ← this hook
  -0.10  Explicit "not useful" (future: /feedback command)
   0.00  No cards injected → nothing happens

Usage:
  python feedback.py "$PROJECT_DIR"
"""

import subprocess
import sys
from pathlib import Path

# Add scripts directory to path for knowledge module import
sys.path.insert(0, str(Path(__file__).parent))

from knowledge import (
    load_index,
    load_session_log,
    save_session_log,
    update_card_score,
    increment_useful,
    find_card_in_index,
    _empty_session_log,
)

# Score adjustments
IMPLICIT_APPLIED_DELTA = +0.10   # Keywords from card found in git diff
IMPLICIT_IGNORED_DELTA = -0.02   # Injected but no keywords in diff


def get_session_diff(project_dir: str | None, git_head: str | None) -> str:
    """Get the combined git diff since session start.

    We check two things:
      1. Committed changes since the recorded HEAD SHA (git log --diff)
      2. Uncommitted changes (staged + unstaged)

    This catches both work that was committed during the session and
    work still in progress when the session ends.

    Returns:
        The combined diff text (lowercased for keyword matching),
        or empty string if not a git repo or no changes.
    """
    if not project_dir:
        return ""

    diff_parts = []

    # Get uncommitted changes (staged + unstaged)
    # This is the most common case — the user worked but didn't commit yet
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            diff_parts.append(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Get committed changes since session start
    # Only if we have a starting SHA to diff from
    if git_head:
        try:
            result = subprocess.run(
                ["git", "diff", git_head, "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                diff_parts.append(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Also include recent commit messages (might reference techniques)
    if git_head:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"{git_head}..HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                diff_parts.append(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return "\n".join(diff_parts).lower()


def check_card_applied(card_name: str, diff_text: str) -> bool:
    """Check if a card's keywords appear in the session's git diff.

    A card is considered "applied" if at least 2 of its keywords
    appear in the diff (or 1 if the card has fewer than 3 keywords).
    We require multiple keyword matches to avoid false positives —
    a single common word like "python" could match anything.

    Args:
        card_name: The card to check.
        diff_text: The lowercased git diff text.

    Returns:
        True if enough keywords matched → card was likely applied.
    """
    if not diff_text:
        return False

    entry = find_card_in_index(card_name)
    if entry is None:
        return False

    keywords = entry.get("keywords", [])
    if not keywords:
        return False

    # Count how many keywords appear in the diff
    hits = sum(1 for kw in keywords if kw.lower() in diff_text)

    # Require at least 2 matches (or 1 if card has < 3 keywords)
    min_hits = min(2, len(keywords))
    return hits >= min_hits


def main():
    # 1. Read what was injected this session
    log = load_session_log()
    injected = log.get("injected_cards", [])

    if not injected:
        # Nothing was injected — nothing to score. Exit silently.
        return

    # 2. Get the git diff since session start
    project_dir = log.get("project_dir")
    git_head = log.get("git_head_at_start")
    diff_text = get_session_diff(project_dir, git_head)

    # 3. Score each injected card based on keyword presence in diff
    results = []  # (card_name, was_applied, new_score)

    for card_name in injected:
        entry = find_card_in_index(card_name)
        if entry is None:
            continue  # Card was removed during the session

        applied = check_card_applied(card_name, diff_text)

        if applied:
            delta = IMPLICIT_APPLIED_DELTA
            increment_useful(card_name)
        else:
            delta = IMPLICIT_IGNORED_DELTA

        new_score = update_card_score(card_name, delta)
        if new_score is not None:
            results.append((card_name, applied, new_score))

    # 4. Output a summary
    if results:
        applied_count = sum(1 for _, applied, _ in results if applied)
        print("📊 FeedFwd — session summary:")
        for card_name, applied, score in results:
            display_name = card_name.replace("-", " ").title()
            if applied:
                marker = "✅ applied"
            else:
                marker = "💤 not referenced"
            print(f"   • {display_name} — {marker} (score: {score:.2f})")

        if applied_count > 0:
            print(f"   {applied_count} card(s) detected in your work this session.")

    # 5. Clear the session log for the next session
    save_session_log(_empty_session_log())


if __name__ == "__main__":
    main()
