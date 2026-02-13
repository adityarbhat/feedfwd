"""
FeedFwd — Stop Hook: Feedback Collector
========================================
Runs automatically when a Claude Code session ends.

What it does:
  1. Reads _session_log.json to see which cards were injected
  2. Gets the git diff since session start (what code was written)
  3. Detects the session type (planning vs code vs mixed)
  4. Scores each card using TWO signals:
     - Session type match: does the card's category fit the session?
     - Keyword match: do the card's keywords appear in the diff?
  5. Outputs a summary and clears the session log

Session-type aware scoring:
  Instead of only checking keywords in git diffs (which biases toward
  code-level cards), we also detect what KIND of session this was.
  A planning-heavy session (lots of .md changes) boosts workflow and
  prompting cards. A code-heavy session boosts technical cards.

  This solves the problem where general workflow cards (like "iterate
  on a plan before coding") can never score via keyword matching
  because their concepts don't appear literally in code diffs.

Scoring matrix:
  Session type matches + keywords in diff  →  +0.10 (strong signal)
  Session type matches + no keywords       →  +0.05 (moderate: right context)
  Session type doesn't match + keywords    →  +0.05 (moderate: keywords found)
  Neither matches                          →  -0.02 (gentle decay)

Boost cap:
  Implicit feedback alone can only raise a card to 0.70.
  Beyond that requires explicit feedback (future /feedback command).
  This prevents auto-detection from inflating scores unchecked.

Usage:
  python feedback.py "$PROJECT_DIR"
"""

import subprocess
import sys
from pathlib import Path

# Add scripts directory to path for knowledge module import
sys.path.insert(0, str(Path(__file__).parent))

from knowledge import (
    load_session_log,
    save_session_log,
    update_card_score,
    increment_useful,
    find_card_in_index,
    _empty_session_log,
)

# ---------------------------------------------------------------------------
# Score adjustments
# ---------------------------------------------------------------------------
STRONG_SIGNAL_DELTA = +0.10    # Session type matches AND keywords in diff
MODERATE_SIGNAL_DELTA = +0.05  # Session type matches OR keywords in diff
IGNORED_DELTA = -0.02          # Neither matches — gentle decay
IMPLICIT_SCORE_CAP = 0.70     # Max score reachable via implicit feedback

# ---------------------------------------------------------------------------
# Session type detection
# ---------------------------------------------------------------------------

# Categories that benefit from planning-type sessions
PLANNING_CATEGORIES = {"workflow", "prompting"}

# Categories that benefit from code-type sessions
CODE_CATEGORIES = {"python", "tools", "testing", "debugging", "architecture"}

# File extensions that indicate planning/documentation work
PLANNING_EXTENSIONS = {".md", ".txt", ".rst", ".doc", ".adoc"}

# File extensions that indicate code implementation work
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".rb", ".php", ".c", ".cpp", ".h", ".cs", ".swift", ".kt",
    ".sh", ".bash", ".zsh", ".sql", ".yaml", ".yml", ".json",
    ".toml", ".cfg", ".ini", ".html", ".css", ".scss",
}


def detect_session_type(diff_text: str, changed_files: list[str]) -> str:
    """Detect whether this was a planning, code, or mixed session.

    Looks at which file types were changed during the session.
    More .md files → planning. More code files → code. Roughly equal → mixed.

    Args:
        diff_text: The full git diff text.
        changed_files: List of file paths that were changed/created.

    Returns:
        "planning", "code", or "mixed"
    """
    planning_count = 0
    code_count = 0

    for filepath in changed_files:
        ext = Path(filepath).suffix.lower()
        if ext in PLANNING_EXTENSIONS:
            planning_count += 1
        elif ext in CODE_EXTENSIONS:
            code_count += 1

    # If no files detected, try to infer from diff content
    if planning_count == 0 and code_count == 0:
        # Look for common markers in the diff text
        if "def " in diff_text or "function " in diff_text or "import " in diff_text:
            code_count += 1
        if "## " in diff_text or "### " in diff_text:
            planning_count += 1

    total = planning_count + code_count
    if total == 0:
        return "mixed"

    planning_ratio = planning_count / total

    if planning_ratio > 0.6:
        return "planning"
    elif planning_ratio < 0.4:
        return "code"
    else:
        return "mixed"


def get_changed_files(project_dir: str | None, git_head: str | None, session_started_at: str | None = None) -> list[str]:
    """Get list of files changed during this session.

    Includes tracked changes (modified, added) and new untracked files
    created after the session started.

    Returns:
        List of relative file paths.
    """
    if not project_dir:
        return []

    files = []

    # Changed tracked files (staged + unstaged)
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            files.extend(result.stdout.strip().split("\n"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Committed changes since session start
    if git_head:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", git_head, "HEAD"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                files.extend(result.stdout.strip().split("\n"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # New untracked files (filtered by session start time)
    session_start_ts = 0.0
    if session_started_at:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(session_started_at)
            session_start_ts = dt.timestamp()
        except (ValueError, TypeError):
            pass

    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            for rel_path in result.stdout.strip().split("\n"):
                full_path = Path(project_dir) / rel_path
                if not full_path.exists():
                    continue
                if session_start_ts and full_path.stat().st_mtime < session_start_ts:
                    continue
                files.append(rel_path)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return list(set(files))  # Deduplicate


def get_session_diff(project_dir: str | None, git_head: str | None, session_started_at: str | None = None) -> str:
    """Get the combined git diff text since session start.

    Includes tracked changes, untracked file content, committed changes,
    and commit messages. All lowercased for keyword matching.
    """
    if not project_dir:
        return ""

    diff_parts = []

    # Uncommitted changes to tracked files
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

    # New untracked files created during session
    session_start_ts = 0.0
    if session_started_at:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(session_started_at)
            session_start_ts = dt.timestamp()
        except (ValueError, TypeError):
            pass

    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            for rel_path in result.stdout.strip().split("\n"):
                full_path = Path(project_dir) / rel_path
                if not full_path.exists() or full_path.stat().st_size > 50_000:
                    continue
                if session_start_ts and full_path.stat().st_mtime < session_start_ts:
                    continue
                try:
                    diff_parts.append(full_path.read_text())
                except Exception:
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Committed changes since session start
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

    # Commit messages since session start
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


def check_card_keywords(card_name: str, diff_text: str) -> bool:
    """Check if a card's keywords appear in the session diff.

    Requires at least 2 keyword matches (or 1 if fewer than 3 keywords)
    to avoid false positives from common words.
    """
    if not diff_text:
        return False

    entry = find_card_in_index(card_name)
    if entry is None:
        return False

    keywords = entry.get("keywords", [])
    if not keywords:
        return False

    hits = sum(1 for kw in keywords if kw.lower() in diff_text)
    min_hits = min(2, len(keywords))
    return hits >= min_hits


def check_session_type_match(card_name: str, session_type: str) -> bool:
    """Check if a card's category aligns with the detected session type.

    Planning sessions match workflow/prompting cards.
    Code sessions match python/tools/testing/debugging/architecture cards.
    Mixed sessions match everything.
    """
    entry = find_card_in_index(card_name)
    if entry is None:
        return False

    category = entry.get("category", "")

    if session_type == "mixed":
        return True  # Everything gets a fair shot in mixed sessions
    elif session_type == "planning":
        return category in PLANNING_CATEGORIES
    elif session_type == "code":
        return category in CODE_CATEGORIES

    return False


def compute_delta(session_match: bool, keyword_match: bool, current_score: float) -> float:
    """Compute the score delta based on session type and keyword signals.

    Scoring matrix:
      session_match + keyword_match  →  +0.10 (strong)
      session_match only             →  +0.05 (moderate)
      keyword_match only             →  +0.05 (moderate)
      neither                        →  -0.02 (gentle decay)

    Applies the implicit boost cap: score can't exceed 0.70 from
    implicit feedback alone.
    """
    if session_match and keyword_match:
        delta = STRONG_SIGNAL_DELTA
    elif session_match or keyword_match:
        delta = MODERATE_SIGNAL_DELTA
    else:
        delta = IGNORED_DELTA

    # Apply boost cap — implicit feedback can't push score above 0.70
    if delta > 0 and current_score + delta > IMPLICIT_SCORE_CAP:
        delta = max(0.0, IMPLICIT_SCORE_CAP - current_score)

    return delta


def main():
    # 1. Read what was injected this session
    log = load_session_log()
    injected = log.get("injected_cards", [])

    if not injected:
        return

    # 2. Get session diff and changed files
    project_dir = log.get("project_dir")
    git_head = log.get("git_head_at_start")
    started_at = log.get("started_at")

    diff_text = get_session_diff(project_dir, git_head, started_at)
    changed_files = get_changed_files(project_dir, git_head, started_at)

    # 3. Detect session type
    session_type = detect_session_type(diff_text, changed_files)

    # 4. Score each injected card
    results = []  # (card_name, session_match, keyword_match, new_score)

    for card_name in injected:
        entry = find_card_in_index(card_name)
        if entry is None:
            continue

        session_match = check_session_type_match(card_name, session_type)
        keyword_match = check_card_keywords(card_name, diff_text)
        current_score = entry.get("score", 0.5)

        delta = compute_delta(session_match, keyword_match, current_score)

        if delta > 0:
            increment_useful(card_name)

        new_score = update_card_score(card_name, delta)
        if new_score is not None:
            results.append((card_name, session_match, keyword_match, new_score))

    # 5. Output summary
    if results:
        type_label = {"planning": "📝 planning", "code": "💻 code", "mixed": "🔀 mixed"}
        print(f"📊 FeedFwd — session summary ({type_label.get(session_type, session_type)}):")

        for card_name, s_match, kw_match, score in results:
            display_name = card_name.replace("-", " ").title()
            if s_match and kw_match:
                marker = "✅ applied (session + keywords)"
            elif s_match:
                marker = "✅ relevant session type"
            elif kw_match:
                marker = "✅ keywords detected"
            else:
                marker = "💤 not referenced"
            print(f"   • {display_name} — {marker} (score: {score:.2f})")

        applied = sum(1 for _, sm, km, _ in results if sm or km)
        if applied > 0:
            print(f"   {applied} card(s) contributed to this session.")

    # 6. Clear session log
    save_session_log(_empty_session_log())


if __name__ == "__main__":
    main()
