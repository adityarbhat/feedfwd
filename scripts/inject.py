"""
FeedFwd — SessionStart Hook: Knowledge Injector
================================================
Runs automatically at the start of every Claude Code session.

What it does:
  1. Loads _index.json from ~/.config/feedfwd/
  2. Reads project context (file types, CLAUDE.md, recent git log)
  3. Scores each knowledge card for relevance to this project
  4. Selects top 2-3 cards (max 400 tokens total)
  5. Prints the injection block to stdout (Claude Code captures this)
  6. Logs injected cards to _session_log.json (for the feedback hook)

How Claude Code uses this:
  The hooks.json config runs this script on SessionStart. Whatever this
  script prints to stdout gets prepended to the session as context.
  The user sees it as a system message at the start of their session.

Relevance scoring formula:
  relevance = keyword_overlap_score * 0.6 + card_score * 0.4

  - keyword_overlap_score: fraction of card keywords found in project context
  - card_score: the card's feedback-adjusted score (0.0-1.0)

Usage:
  python inject.py "$PROJECT_DIR"
"""

import subprocess
import sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

# Add scripts directory to path for knowledge module import
sys.path.insert(0, str(Path(__file__).parent))

from knowledge import (
    KNOWLEDGE_CARDS_DIR,
    MAX_CARDS_PER_SESSION,
    MAX_SESSION_TOKENS,
    load_index,
    load_session_log,
    save_session_log,
    read_card,
    increment_surfaced,
)

# Minimum relevance score to inject a card. Cards scoring below this
# threshold are skipped — no point injecting something irrelevant.
MIN_RELEVANCE = 0.2

# Approximate token overhead for the injection header and formatting
# (the "📚 FeedFwd — active learnings..." line plus bullet markers).
HEADER_TOKENS = 25


def get_project_context(project_dir: Path) -> dict:
    """Gather signals about what this project is about.

    We collect three types of context to match against card keywords:
      1. File extensions — what languages/frameworks are in use
      2. CLAUDE.md content — project-specific instructions and keywords
      3. Recent git log — what the developer has been working on lately

    Returns a dict with:
      - file_extensions: set of extensions like {".py", ".ts", ".md"}
      - file_names: set of filenames present (for matching file_patterns)
      - text_context: combined text from CLAUDE.md + git log (for keyword matching)
    """
    context = {
        "file_extensions": set(),
        "file_names": set(),
        "text_context": "",
    }

    if not project_dir.exists():
        return context

    # 1. Scan file extensions and names (top 2 levels only — don't recurse into node_modules etc.)
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".claude-plugin", "venv", ".next", "dist", "build"}
    for item in project_dir.iterdir():
        if item.name.startswith(".") and item.name in skip_dirs:
            continue
        if item.is_file():
            context["file_extensions"].add(item.suffix)
            context["file_names"].add(item.name)
        elif item.is_dir() and item.name not in skip_dirs:
            try:
                for sub_item in item.iterdir():
                    if sub_item.is_file():
                        context["file_extensions"].add(sub_item.suffix)
                        context["file_names"].add(sub_item.name)
            except PermissionError:
                pass

    # 2. Read CLAUDE.md if it exists (contains project-specific instructions)
    text_parts = []
    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        try:
            text_parts.append(claude_md.read_text()[:2000])  # Cap at 2000 chars
        except Exception:
            pass

    # 3. Recent git log (last 5 commit messages — what has the dev been working on?)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--no-decorate"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            text_parts.append(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    context["text_context"] = " ".join(text_parts).lower()

    return context


def score_card(card_entry: dict, context: dict) -> float:
    """Score a card's relevance to the current project.

    Formula: relevance = keyword_overlap * 0.6 + card_score * 0.4

    keyword_overlap is computed from three signals:
      - Do the card's keywords appear in the project's text context?
      - Do the card's file_patterns match files in the project?
      - Do the card's task_types appear in the text context?

    Args:
        card_entry: A card's index entry (from _index.json).
        context: Project context from get_project_context().

    Returns:
        A relevance score between 0.0 and 1.0.
    """
    keywords = card_entry.get("keywords", [])
    file_patterns = card_entry.get("file_patterns", [])
    task_types = card_entry.get("task_types", [])
    card_score = card_entry.get("score", 0.5)

    if not keywords and not file_patterns:
        # Card has no triggers — can't score it
        return card_score * 0.4

    # Signal 1: Keyword matches in text context
    # Check if each keyword appears in the combined text (CLAUDE.md + git log)
    text = context["text_context"]
    keyword_hits = 0
    for kw in keywords:
        if kw.lower() in text:
            keyword_hits += 1

    keyword_score = keyword_hits / len(keywords) if keywords else 0.0

    # Signal 2: File pattern matches
    # Check if the card's file_patterns match any files in the project
    pattern_hits = 0
    if file_patterns:
        all_names = context["file_names"]
        all_extensions = context["file_extensions"]
        for pattern in file_patterns:
            # Check against extensions (e.g., "*.py" matches ".py" extension)
            for ext in all_extensions:
                if fnmatch(f"file{ext}", pattern):
                    pattern_hits += 1
                    break
            else:
                # Check against actual filenames
                for name in all_names:
                    if fnmatch(name, pattern):
                        pattern_hits += 1
                        break

        pattern_score = pattern_hits / len(file_patterns)
    else:
        pattern_score = 0.0

    # Combine keyword and pattern scores (keywords weighted higher)
    overlap_score = keyword_score * 0.7 + pattern_score * 0.3

    # Final relevance: overlap * 0.6 + card_score * 0.4
    relevance = overlap_score * 0.6 + card_score * 0.4

    return relevance


def select_cards(index: dict, context: dict) -> list[tuple[dict, float]]:
    """Select the top cards for injection based on relevance.

    Applies the token budget: max 3 cards, max 400 total tokens.
    Only includes cards with relevance > MIN_RELEVANCE.

    Returns:
        List of (card_entry, relevance_score) tuples, sorted by relevance.
    """
    # Score all cards
    scored = []
    for card_entry in index["cards"]:
        relevance = score_card(card_entry, context)
        if relevance > MIN_RELEVANCE:
            scored.append((card_entry, relevance))

    # Sort by relevance (highest first)
    scored.sort(key=lambda x: x[1], reverse=True)

    # Apply budget constraints
    selected = []
    total_tokens = HEADER_TOKENS  # Reserve space for the header

    for card_entry, relevance in scored:
        if len(selected) >= MAX_CARDS_PER_SESSION:
            break

        card_tokens = card_entry.get("injection_tokens", 0)
        if total_tokens + card_tokens > MAX_SESSION_TOKENS:
            continue  # Skip this card, try the next (it might be smaller)

        selected.append((card_entry, relevance))
        total_tokens += card_tokens

    return selected


def format_injection(selected: list[tuple[dict, float]]) -> str:
    """Format the injection block that gets printed to stdout.

    This is the actual text that appears at the start of the user's
    Claude Code session. Keep it concise — every token counts.

    Output format:
      📚 FeedFwd — active learnings for this session:
      • [Card Name] Injection text here...
      • [Card Name] Injection text here...
    """
    lines = ["📚 FeedFwd — active learnings for this session:"]

    for card_entry, _relevance in selected:
        # Read the full card to get the injection text
        card_path = KNOWLEDGE_CARDS_DIR / card_entry["file"]
        if not card_path.exists():
            continue

        card = read_card(card_path)
        # Format: bullet with card name in brackets, then injection text
        display_name = card.name.replace("-", " ").title()
        lines.append(f"• [{display_name}] {card.injection_text}")

    return "\n".join(lines)


def _get_git_head(project_dir: Path) -> str | None:
    """Get the current git HEAD SHA, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def main():
    # Get the project directory from the command line argument
    if len(sys.argv) > 1:
        project_dir = Path(sys.argv[1])
    else:
        project_dir = Path.cwd()

    # 1. Load the index
    index = load_index()
    if not index["cards"]:
        # No cards in the knowledge base — exit silently
        return

    # 2. Read project context
    context = get_project_context(project_dir)

    # 3. Select relevant cards
    selected = select_cards(index, context)
    if not selected:
        # No cards relevant enough — exit silently
        return

    # 4. Format and print the injection block
    injection = format_injection(selected)
    print(injection)

    # 5. Log what was injected (for the feedback hook)
    # We also record the git HEAD SHA so feedback.py can diff against it
    # to detect if injected knowledge was actually applied in the code.
    git_head = _get_git_head(project_dir)
    log = {
        "session_id": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "project_dir": str(project_dir),
        "git_head_at_start": git_head,
        "injected_cards": [card["name"] for card, _ in selected],
    }
    save_session_log(log)

    # 6. Increment times_surfaced for each injected card
    for card_entry, _ in selected:
        increment_surfaced(card_entry["name"])


if __name__ == "__main__":
    main()
