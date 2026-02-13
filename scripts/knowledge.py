"""
FeedFwd — Knowledge Card Utilities
====================================
Core module that every other FeedFwd component imports.

This handles the data model and all I/O for knowledge cards and the
index cache. Think of it as the "database layer" for FeedFwd — except
the database is just markdown files + a JSON index.

Architecture:
  - Knowledge cards are .md files with YAML frontmatter (human-readable)
  - _index.json is a JSON cache for fast lookups (machine-readable)
  - Every write operation updates BOTH the .md file AND _index.json
  - If they ever get out of sync, rebuild_index() re-scans all cards

Dependencies:
  - python-frontmatter: reads/writes markdown files with YAML headers
  - tiktoken: counts tokens to enforce the 250-token injection cap
  - pathlib: modern Python path handling (built-in)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter
import tiktoken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Where the user's knowledge base lives (outside the plugin directory
# so it survives plugin updates and works across all projects).
KNOWLEDGE_BASE_DIR = Path.home() / ".config" / "feedfwd"
KNOWLEDGE_CARDS_DIR = KNOWLEDGE_BASE_DIR / "knowledge"
INDEX_PATH = KNOWLEDGE_BASE_DIR / "_index.json"
SESSION_LOG_PATH = KNOWLEDGE_BASE_DIR / "_session_log.json"

# Default categories — each becomes a subdirectory under knowledge/
DEFAULT_CATEGORIES = [
    "prompting",
    "python",
    "workflow",
    "tools",
    "testing",
    "architecture",
    "debugging",
]

# Token counting uses cl100k_base, which is a close approximation of
# Claude's tokenizer. Not exact, but good enough for budget management.
TOKENIZER_ENCODING = "cl100k_base"

# Card limits from the spec
MAX_INJECTION_TOKENS = 250  # per card
MAX_SESSION_TOKENS = 400    # total injection budget per session
MAX_CARDS_PER_SESSION = 3
DEFAULT_SCORE = 0.50
MIN_SCORE = 0.0
MAX_SCORE = 1.0

# Duplicate detection threshold — if two cards share this fraction
# of keywords, the newer one is considered a duplicate.
DUPLICATE_KEYWORD_OVERLAP = 0.60


# ---------------------------------------------------------------------------
# Token Counting
# ---------------------------------------------------------------------------

# We load the tokenizer once at module level so we don't pay the
# initialization cost on every call. This is a common Python pattern
# called "module-level singleton."
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Lazy-load the tiktoken encoder (only initialized on first use)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding(TOKENIZER_ENCODING)
    return _encoder


def count_tokens(text: str) -> int:
    """Count the number of tokens in a string.

    Used to enforce the 250-token cap on injection text and the
    400-token session budget. Returns 0 for empty/None input.
    """
    if not text:
        return 0
    return len(_get_encoder().encode(text))


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class Triggers:
    """What signals make a knowledge card relevant to a session.

    keywords:      Words that would appear in user prompts or code when
                   this technique is relevant (e.g., "async", "generator").
    file_patterns: Glob patterns for file types (e.g., "*.py", "*.tsx").
    task_types:    High-level task categories (e.g., "debugging", "refactoring").
    """
    keywords: list[str] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)


@dataclass
class KnowledgeCard:
    """In-memory representation of a FeedFwd knowledge card.

    This maps 1:1 to the YAML frontmatter + markdown sections in the
    .md file on disk. We use a dataclass (rather than a plain dict)
    so the schema is explicit and we get type checking for free.

    Fields match the spec in skills/distiller/SKILL.md.
    """
    # --- Identity ---
    name: str                          # kebab-case identifier (= filename without .md)
    source: str                        # URL, "pasted-text", or "screenshot"
    captured: str                      # ISO date string: "2026-02-12"
    category: str                      # subdirectory name under knowledge/

    # --- Scoring ---
    score: float = DEFAULT_SCORE       # 0.0–1.0, starts at 0.50
    times_surfaced: int = 0            # how many sessions this was injected into
    times_useful: int = 0              # how many positive feedback signals

    # --- Triggers (for relevance matching) ---
    triggers: Triggers = field(default_factory=Triggers)

    # --- Content ---
    injection_tokens: int = 0          # pre-computed token count of injection text
    insight: str = ""                  # 2-3 sentence summary (never injected)
    injection_text: str = ""           # the actual text injected into sessions
    example: str = ""                  # before/after example

    @property
    def file_path(self) -> Path:
        """Full path to this card's .md file on disk."""
        return KNOWLEDGE_CARDS_DIR / self.category / f"{self.name}.md"

    @property
    def relative_path(self) -> str:
        """Relative path from the knowledge dir (e.g., 'prompting/ultrathink.md')."""
        return f"{self.category}/{self.name}.md"


# ---------------------------------------------------------------------------
# Card I/O — Reading and Writing .md Files
# ---------------------------------------------------------------------------

def read_card(path: Path) -> KnowledgeCard:
    """Read a knowledge card from a .md file.

    Uses python-frontmatter to parse the YAML header and markdown body.
    The markdown body is split into sections (Insight, Injection Text,
    Example) by looking for ## headings.

    Args:
        path: Full path to the .md file.

    Returns:
        A KnowledgeCard instance with all fields populated.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file is missing required frontmatter fields.
    """
    post = frontmatter.load(str(path))
    meta = post.metadata

    # Parse the markdown body into sections by splitting on ## headings.
    # This is simple string parsing — we look for lines starting with "## ".
    sections = _parse_sections(post.content)

    # Build the Triggers from the nested YAML structure.
    # The YAML might have triggers as a dict with sub-keys, or it might
    # be missing entirely — we handle both cases with .get() defaults.
    triggers_raw = meta.get("triggers", {})
    triggers = Triggers(
        keywords=triggers_raw.get("keywords", []),
        file_patterns=triggers_raw.get("file_patterns", []),
        task_types=triggers_raw.get("task_types", []),
    )

    return KnowledgeCard(
        name=meta["name"],
        source=meta.get("source", ""),
        captured=str(meta.get("captured", "")),
        category=meta.get("category", ""),
        score=float(meta.get("score", DEFAULT_SCORE)),
        times_surfaced=int(meta.get("times_surfaced", 0)),
        times_useful=int(meta.get("times_useful", 0)),
        triggers=triggers,
        injection_tokens=int(meta.get("injection_tokens", 0)),
        insight=sections.get("Insight", "").strip(),
        injection_text=sections.get("Injection Text", "").strip(),
        example=sections.get("Example", "").strip(),
    )


def write_card(card: KnowledgeCard) -> Path:
    """Write a knowledge card to disk as a .md file with YAML frontmatter.

    Creates the category directory if it doesn't exist. Overwrites any
    existing file at the same path (used for score updates too).

    Args:
        card: The KnowledgeCard to write.

    Returns:
        The Path where the file was written.
    """
    # Ensure the category directory exists
    card.file_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the YAML frontmatter as a dict.
    # python-frontmatter will serialize this to YAML automatically.
    metadata = {
        "name": card.name,
        "source": card.source,
        "captured": card.captured,
        "category": card.category,
        "score": round(card.score, 2),
        "times_surfaced": card.times_surfaced,
        "times_useful": card.times_useful,
        "triggers": {
            "keywords": card.triggers.keywords,
            "file_patterns": card.triggers.file_patterns,
            "task_types": card.triggers.task_types,
        },
        "injection_tokens": card.injection_tokens,
    }

    # Build the markdown body from the three sections.
    body_parts = []
    if card.insight:
        body_parts.append(f"## Insight\n\n{card.insight}")
    if card.injection_text:
        body_parts.append(f"## Injection Text\n\n{card.injection_text}")
    if card.example:
        body_parts.append(f"## Example\n\n{card.example}")

    body = "\n\n".join(body_parts)

    # Create the frontmatter Post object and write it.
    # python-frontmatter handles the --- delimiters automatically.
    post = frontmatter.Post(body, **metadata)
    card.file_path.write_text(frontmatter.dumps(post) + "\n")

    return card.file_path


def delete_card_file(card_name: str, category: str) -> bool:
    """Delete a card's .md file from disk.

    Args:
        card_name: The kebab-case name of the card.
        category: The category directory it lives in.

    Returns:
        True if the file was deleted, False if it didn't exist.
    """
    path = KNOWLEDGE_CARDS_DIR / category / f"{card_name}.md"
    if path.exists():
        path.unlink()
        return True
    return False


def _parse_sections(markdown_body: str) -> dict[str, str]:
    """Split a markdown body into sections by ## headings.

    Given:
        ## Insight
        Some text here.

        ## Injection Text
        More text here.

    Returns:
        {"Insight": "Some text here.", "Injection Text": "More text here."}

    This is intentionally simple — we just split on lines starting
    with "## " and use the heading text as the key.
    """
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in markdown_body.split("\n"):
        if line.startswith("## "):
            # Save the previous section (if any)
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines)
            # Start a new section
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section
    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines)

    return sections


# ---------------------------------------------------------------------------
# Index I/O — Reading and Writing _index.json
# ---------------------------------------------------------------------------

def load_index() -> dict:
    """Load the _index.json file.

    The index is a JSON cache of card metadata for fast lookups.
    The SessionStart hook reads this instead of parsing every .md file.

    Returns:
        The parsed JSON as a dict with keys: version, last_updated, cards.
        If the file doesn't exist or is corrupt, returns a fresh empty index.
    """
    if not INDEX_PATH.exists():
        return _empty_index()

    try:
        data = json.loads(INDEX_PATH.read_text())
        # Basic validation — make sure it has the expected shape
        if "cards" not in data:
            return _empty_index()
        return data
    except (json.JSONDecodeError, KeyError):
        return _empty_index()


def save_index(index: dict) -> None:
    """Write the _index.json file.

    Updates the last_updated timestamp automatically. Writes with
    indent=2 for human readability (you can open this file and
    inspect it — that's intentional).

    Args:
        index: The full index dict to write.
    """
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")


def _empty_index() -> dict:
    """Return a fresh, empty index structure."""
    return {
        "version": 1,
        "last_updated": None,
        "cards": [],
    }


def card_to_index_entry(card: KnowledgeCard) -> dict:
    """Convert a KnowledgeCard to its _index.json representation.

    The index entry is a subset of the full card — just the metadata
    needed for fast lookups and relevance scoring. It doesn't include
    the full insight/injection_text/example content.
    """
    return {
        "name": card.name,
        "file": card.relative_path,
        "category": card.category,
        "score": round(card.score, 2),
        "times_surfaced": card.times_surfaced,
        "times_useful": card.times_useful,
        "injection_tokens": card.injection_tokens,
        "keywords": card.triggers.keywords,
        "file_patterns": card.triggers.file_patterns,
        "task_types": card.triggers.task_types,
    }


def add_card_to_index(card: KnowledgeCard) -> None:
    """Add a new card to _index.json (or replace if name already exists).

    This is called after write_card() to keep the index in sync.
    """
    index = load_index()

    # Remove existing entry with the same name (if updating)
    index["cards"] = [c for c in index["cards"] if c["name"] != card.name]

    # Add the new entry
    index["cards"].append(card_to_index_entry(card))
    save_index(index)


def remove_card_from_index(card_name: str) -> bool:
    """Remove a card from _index.json by name.

    Returns:
        True if the card was found and removed, False if not found.
    """
    index = load_index()
    original_count = len(index["cards"])
    index["cards"] = [c for c in index["cards"] if c["name"] != card_name]

    if len(index["cards"]) < original_count:
        save_index(index)
        return True
    return False


def update_card_in_index(card_name: str, **updates) -> bool:
    """Update specific fields of a card in _index.json.

    This is used by the feedback hook to update scores without
    rewriting the entire index. Pass field names as keyword args:

        update_card_in_index("ultrathink", score=0.65, times_useful=3)

    Returns:
        True if the card was found and updated, False if not found.
    """
    index = load_index()

    for entry in index["cards"]:
        if entry["name"] == card_name:
            for key, value in updates.items():
                if key in entry:
                    entry[key] = value
            save_index(index)
            return True

    return False


def find_card_in_index(card_name: str) -> Optional[dict]:
    """Look up a card in the index by name.

    Returns:
        The index entry dict, or None if not found.
    """
    index = load_index()
    for entry in index["cards"]:
        if entry["name"] == card_name:
            return entry
    return None


def rebuild_index() -> dict:
    """Rebuild _index.json from scratch by scanning all .md files.

    This is the "nuclear option" — if the index gets corrupted or
    out of sync, this re-reads every card file and regenerates the
    index. Normally you shouldn't need this because every write
    operation updates the index incrementally.

    Returns:
        The newly built index dict.
    """
    index = _empty_index()

    if not KNOWLEDGE_CARDS_DIR.exists():
        save_index(index)
        return index

    # Walk all .md files in all category subdirectories
    for md_file in sorted(KNOWLEDGE_CARDS_DIR.rglob("*.md")):
        try:
            card = read_card(md_file)
            index["cards"].append(card_to_index_entry(card))
        except Exception as e:
            # Skip files that can't be parsed — don't let one bad
            # card break the entire index rebuild.
            print(f"Warning: Could not parse {md_file}: {e}")

    save_index(index)
    return index


# ---------------------------------------------------------------------------
# Duplicate Detection
# ---------------------------------------------------------------------------

def find_duplicates(
    keywords: list[str],
    card_name: str,
    threshold: float = DUPLICATE_KEYWORD_OVERLAP,
) -> Optional[dict]:
    """Check if a proposed card duplicates an existing one.

    Compares the proposed card's keywords against every existing card
    in the index. If any existing card has ≥60% keyword overlap, it's
    considered a duplicate.

    How overlap is calculated:
        overlap = len(shared_keywords) / len(proposed_keywords)

    So if you propose 5 keywords and 3 of them match an existing card,
    that's 60% overlap → duplicate.

    Args:
        keywords: The proposed card's trigger keywords (lowercased).
        card_name: The proposed card's name (for fuzzy name matching).
        threshold: Overlap fraction to trigger duplicate (default 0.60).

    Returns:
        The index entry of the duplicate card, or None if no duplicate.
    """
    index = load_index()
    proposed_kw = {kw.lower() for kw in keywords} if keywords else set()
    proposed_name = card_name.lower()

    for entry in index["cards"]:
        # Check 1: Exact name match (always checked, even with no keywords)
        existing_name = entry["name"].lower()
        if existing_name == proposed_name:
            return entry

        # Check 2: Keyword overlap (only if we have keywords to compare)
        if not proposed_kw:
            continue

        existing_kw = {kw.lower() for kw in entry.get("keywords", [])}
        if not existing_kw:
            continue

        shared = proposed_kw & existing_kw
        overlap = len(shared) / len(proposed_kw)

        if overlap >= threshold:
            return entry

    return None


# ---------------------------------------------------------------------------
# Score Management
# ---------------------------------------------------------------------------

def update_card_score(card_name: str, delta: float) -> Optional[float]:
    """Update a card's score by a delta amount.

    Updates both the .md file on disk and the _index.json cache.
    The score is clamped to [0.0, 1.0].

    Args:
        card_name: The kebab-case name of the card.
        delta: Amount to add (positive) or subtract (negative).

    Returns:
        The new score, or None if the card wasn't found.
    """
    # First, find the card in the index to get its file path
    entry = find_card_in_index(card_name)
    if entry is None:
        return None

    # Read the full card from disk
    card_path = KNOWLEDGE_CARDS_DIR / entry["file"]
    if not card_path.exists():
        return None

    card = read_card(card_path)

    # Apply the delta and clamp
    card.score = max(MIN_SCORE, min(MAX_SCORE, card.score + delta))

    # Write back to both .md and index
    write_card(card)
    update_card_in_index(card_name, score=round(card.score, 2))

    return card.score


def increment_surfaced(card_name: str) -> None:
    """Increment times_surfaced for a card (called by inject.py)."""
    entry = find_card_in_index(card_name)
    if entry is None:
        return

    card_path = KNOWLEDGE_CARDS_DIR / entry["file"]
    if not card_path.exists():
        return

    card = read_card(card_path)
    card.times_surfaced += 1
    write_card(card)
    update_card_in_index(card_name, times_surfaced=card.times_surfaced)


def increment_useful(card_name: str) -> None:
    """Increment times_useful for a card (called by feedback.py)."""
    entry = find_card_in_index(card_name)
    if entry is None:
        return

    card_path = KNOWLEDGE_CARDS_DIR / entry["file"]
    if not card_path.exists():
        return

    card = read_card(card_path)
    card.times_useful += 1
    write_card(card)
    update_card_in_index(card_name, times_useful=card.times_useful)


# ---------------------------------------------------------------------------
# Session Log
# ---------------------------------------------------------------------------

def load_session_log() -> dict:
    """Load _session_log.json (tracks what was injected this session).

    The inject.py hook writes this, and the feedback.py hook reads it
    to know which cards to ask about.

    Returns:
        The session log dict, or a fresh empty log if file is missing.
    """
    if not SESSION_LOG_PATH.exists():
        return _empty_session_log()

    try:
        return json.loads(SESSION_LOG_PATH.read_text())
    except (json.JSONDecodeError, KeyError):
        return _empty_session_log()


def save_session_log(log: dict) -> None:
    """Write _session_log.json."""
    SESSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_LOG_PATH.write_text(json.dumps(log, indent=2) + "\n")


def _empty_session_log() -> dict:
    """Return a fresh, empty session log."""
    return {
        "session_id": None,
        "started_at": None,
        "injected_cards": [],
    }


# ---------------------------------------------------------------------------
# Convenience: Full Card Lifecycle
# ---------------------------------------------------------------------------

def create_card(
    name: str,
    source: str,
    category: str,
    insight: str,
    injection_text: str,
    example: str,
    keywords: list[str],
    file_patterns: list[str] | None = None,
    task_types: list[str] | None = None,
    score: float = DEFAULT_SCORE,
) -> KnowledgeCard:
    """Create a new knowledge card: write the .md file and update the index.

    This is the main entry point for creating cards. It:
    1. Counts tokens in the injection text
    2. Builds the KnowledgeCard dataclass
    3. Writes the .md file to the category directory
    4. Adds the card to _index.json

    Args:
        name: Kebab-case identifier (becomes the filename).
        source: URL or "pasted-text" or "screenshot".
        category: Category subdirectory name.
        insight: 2-3 sentence summary (for human reference).
        injection_text: The text that gets injected into sessions.
        example: Before/after example text.
        keywords: Trigger keywords for relevance matching.
        file_patterns: Glob patterns for relevant file types.
        task_types: High-level task categories.
        score: Initial score (default 0.50).

    Returns:
        The created KnowledgeCard instance.
    """
    token_count = count_tokens(injection_text)

    card = KnowledgeCard(
        name=name,
        source=source,
        captured=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        category=category,
        score=score,
        triggers=Triggers(
            keywords=keywords,
            file_patterns=file_patterns or [],
            task_types=task_types or [],
        ),
        injection_tokens=token_count,
        insight=insight,
        injection_text=injection_text,
        example=example,
    )

    # Write to disk and update the index
    write_card(card)
    add_card_to_index(card)

    return card


def remove_card(card_name: str) -> bool:
    """Remove a card completely: delete the .md file and update the index.

    Args:
        card_name: The kebab-case name of the card.

    Returns:
        True if the card was found and removed, False otherwise.
    """
    entry = find_card_in_index(card_name)
    if entry is None:
        return False

    # Delete the file
    delete_card_file(card_name, entry["category"])

    # Remove from index
    remove_card_from_index(card_name)

    return True
