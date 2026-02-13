"""
FeedFwd — Card CLI Helper
===========================
A command-line interface to the knowledge.py utilities, used by both
the distiller subagent and the /knowledge command.

Distiller commands (called via Bash by the subagent):
  python scripts/card_cli.py check-dup --name "card-name" --keywords "kw1,kw2,kw3"
  python scripts/card_cli.py count-tokens "text to count"
  python scripts/card_cli.py index-add /path/to/card.md

Knowledge management commands (called by the /knowledge command):
  python scripts/card_cli.py list
  python scripts/card_cli.py search <term>
  python scripts/card_cli.py show <name>
  python scripts/card_cli.py remove <name>
  python scripts/card_cli.py stats

Each command prints its result to stdout. Exit code 0 = success, 1 = error.
"""

import sys
from pathlib import Path

# Add the scripts directory to the import path so we can import knowledge.py
# regardless of what directory this script is called from.
sys.path.insert(0, str(Path(__file__).parent))

from knowledge import (
    KNOWLEDGE_CARDS_DIR,
    count_tokens,
    find_card_in_index,
    find_duplicates,
    load_index,
    read_card,
    remove_card,
    add_card_to_index,
    remove_card_from_index,
    rebuild_index,
)


def cmd_check_dup(args: list[str]) -> int:
    """Check if a proposed card would be a duplicate.

    Usage: card_cli.py check-dup --name "card-name" --keywords "kw1,kw2,kw3"

    Prints either:
      DUPLICATE: <existing-card-name>
      NO_DUPLICATE
    """
    name = ""
    keywords: list[str] = []

    # Simple argument parsing (no external deps needed)
    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]
            i += 2
        elif args[i] == "--keywords" and i + 1 < len(args):
            keywords = [kw.strip() for kw in args[i + 1].split(",") if kw.strip()]
            i += 2
        else:
            i += 1

    if not name and not keywords:
        print("Error: provide --name and/or --keywords", file=sys.stderr)
        return 1

    dup = find_duplicates(keywords, name)
    if dup:
        print(f"DUPLICATE: {dup['name']}")
    else:
        print("NO_DUPLICATE")
    return 0


def cmd_count_tokens(args: list[str]) -> int:
    """Count tokens in a text string.

    Usage: card_cli.py count-tokens "text to count"

    Prints the token count as a plain integer.
    """
    if not args:
        print("Error: provide text to count", file=sys.stderr)
        return 1

    text = " ".join(args)
    tokens = count_tokens(text)
    print(tokens)
    return 0


def cmd_index_add(args: list[str]) -> int:
    """Add a card to _index.json by reading its .md file.

    Usage: card_cli.py index-add /path/to/card.md

    Reads the .md file, extracts metadata, and adds/updates the
    entry in _index.json. Prints confirmation.
    """
    if not args:
        print("Error: provide path to .md file", file=sys.stderr)
        return 1

    path = Path(args[0]).expanduser()
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    try:
        card = read_card(path)
        add_card_to_index(card)
        print(f"INDEXED: {card.name} → {card.relative_path}")
        return 0
    except Exception as e:
        print(f"Error reading card: {e}", file=sys.stderr)
        return 1


def cmd_index_remove(args: list[str]) -> int:
    """Remove a card from _index.json by name.

    Usage: card_cli.py index-remove card-name
    """
    if not args:
        print("Error: provide card name", file=sys.stderr)
        return 1

    removed = remove_card_from_index(args[0])
    if removed:
        print(f"REMOVED: {args[0]}")
    else:
        print(f"NOT_FOUND: {args[0]}")
    return 0


def cmd_index_rebuild(args: list[str]) -> int:
    """Rebuild _index.json from all .md files on disk.

    Usage: card_cli.py index-rebuild
    """
    index = rebuild_index()
    print(f"REBUILT: {len(index['cards'])} cards indexed")
    return 0


def cmd_index_list(args: list[str]) -> int:
    """List all cards in the index.

    Usage: card_cli.py index-list
    """
    index = load_index()
    if not index["cards"]:
        print("(empty — no cards yet)")
        return 0

    for entry in index["cards"]:
        print(f"  {entry['name']} → {entry['file']} (score: {entry['score']})")
    print(f"\nTotal: {len(index['cards'])} cards")
    return 0


def cmd_list(args: list[str]) -> int:
    """List all cards grouped by category, sorted by score.

    Usage: card_cli.py list

    Produces formatted output matching the spec's /knowledge display.
    """
    index = load_index()
    cards = index["cards"]

    if not cards:
        print("📚 FeedFwd Knowledge Base (0 cards)")
        print("\n  No cards yet. Run /learn <url> to capture your first one.")
        return 0

    # Group cards by category
    by_category: dict[str, list[dict]] = {}
    for card in cards:
        cat = card["category"]
        by_category.setdefault(cat, []).append(card)

    # Sort each category's cards by score (highest first)
    for cat in by_category:
        by_category[cat].sort(key=lambda c: c["score"], reverse=True)

    print(f"📚 FeedFwd Knowledge Base ({len(cards)} cards)")
    print()

    # Print each category, sorted alphabetically
    for cat in sorted(by_category.keys()):
        cat_cards = by_category[cat]
        print(f"{cat}/ ({len(cat_cards)} cards)")
        for c in cat_cards:
            surfaced = c["times_surfaced"]
            useful = c["times_useful"]
            if surfaced == 0:
                status = "new — not yet surfaced"
            else:
                status = f"surfaced {surfaced}x, useful {useful}x"
            print(f"  ★ {c['score']:.2f}  {c['name']:<35s} ({status})")
        print()

    return 0


def cmd_search(args: list[str]) -> int:
    """Full-text search across card keywords, names, and content.

    Usage: card_cli.py search <term>

    Searches card names, keywords, categories, and (if needed) the
    actual .md file content. Prints matching cards.
    """
    if not args:
        print("Error: provide a search term", file=sys.stderr)
        return 1

    term = " ".join(args).lower()
    index = load_index()
    matches = []

    for card in index["cards"]:
        # Search in name, category, and keywords
        searchable = (
            card["name"].lower()
            + " " + card["category"].lower()
            + " " + " ".join(kw.lower() for kw in card.get("keywords", []))
        )
        if term in searchable:
            matches.append((card, "metadata"))
            continue

        # If not found in metadata, search in the actual file content
        card_path = KNOWLEDGE_CARDS_DIR / card["file"]
        if card_path.exists():
            content = card_path.read_text().lower()
            if term in content:
                matches.append((card, "content"))

    if not matches:
        print(f"No cards matching '{term}'")
        return 0

    print(f"🔍 {len(matches)} card(s) matching '{term}':")
    print()
    for card, match_type in matches:
        print(f"  ★ {card['score']:.2f}  {card['name']} → {card['file']}")
    print()
    return 0


def cmd_show(args: list[str]) -> int:
    """Display a specific card's full content.

    Usage: card_cli.py show <name>

    Prints the full .md file content (frontmatter + all sections).
    """
    if not args:
        print("Error: provide a card name", file=sys.stderr)
        return 1

    name = args[0]
    entry = find_card_in_index(name)
    if entry is None:
        print(f"Card not found: '{name}'")
        # Suggest similar names
        index = load_index()
        suggestions = [c["name"] for c in index["cards"] if name.lower() in c["name"].lower()]
        if suggestions:
            print(f"Did you mean: {', '.join(suggestions)}?")
        return 1

    card_path = KNOWLEDGE_CARDS_DIR / entry["file"]
    if not card_path.exists():
        print(f"Card file missing: {card_path}", file=sys.stderr)
        return 1

    # Print the full card with a header
    card = read_card(card_path)
    print(f"📄 {card.name} ({card.category}/)")
    print(f"   Source: {card.source}")
    print(f"   Captured: {card.captured}")
    print(f"   Score: {card.score:.2f} (surfaced {card.times_surfaced}x, useful {card.times_useful}x)")
    print(f"   Keywords: {', '.join(card.triggers.keywords)}")
    print(f"   Injection tokens: {card.injection_tokens}")
    print()
    print("── Insight ──")
    print(card.insight)
    print()
    print("── Injection Text ──")
    print(card.injection_text)
    print()
    print("── Example ──")
    print(card.example)
    print()
    print(f"📁 File: {card_path}")
    return 0


def cmd_remove(args: list[str]) -> int:
    """Remove a card completely (deletes .md file and updates index).

    Usage: card_cli.py remove <name>
    """
    if not args:
        print("Error: provide a card name", file=sys.stderr)
        return 1

    name = args[0]
    removed = remove_card(name)
    if removed:
        print(f"🗑️  Removed: {name}")
    else:
        print(f"Card not found: '{name}'")
    return 0


def cmd_stats(args: list[str]) -> int:
    """Show knowledge base statistics.

    Usage: card_cli.py stats

    Displays total cards, active count, average score, top and
    low performers.
    """
    index = load_index()
    cards = index["cards"]

    if not cards:
        print("📊 FeedFwd Stats")
        print("Total cards: 0")
        print("\nNo cards yet. Run /learn <url> to get started.")
        return 0

    scores = [c["score"] for c in cards]
    active = [c for c in cards if c["score"] > 0.3]
    avg_score = sum(scores) / len(scores)

    # Sort by score for top/low performers
    sorted_cards = sorted(cards, key=lambda c: c["score"], reverse=True)

    print("📊 FeedFwd Stats")
    print(f"Total cards: {len(cards)}")
    print(f"Active (score > 0.3): {len(active)}")
    print(f"Average score: {avg_score:.2f}")

    # Top performers (up to 3)
    top = sorted_cards[:3]
    if top:
        print()
        print("Top performers:")
        for c in top:
            surfaced = c["times_surfaced"]
            useful = c["times_useful"]
            print(f"  ★ {c['score']:.2f}  {c['name']:<35s} ({surfaced} sessions, {useful} useful)")

    # Low performers (score <= 0.3, up to 3)
    low = [c for c in sorted_cards if c["score"] <= 0.3]
    if low:
        print()
        print("Low performers (consider removing):")
        for c in low[:3]:
            surfaced = c["times_surfaced"]
            useful = c["times_useful"]
            print(f"  ★ {c['score']:.2f}  {c['name']:<35s} ({surfaced} sessions, {useful} useful)")

    return 0


COMMANDS = {
    "check-dup": cmd_check_dup,
    "count-tokens": cmd_count_tokens,
    "index-add": cmd_index_add,
    "index-remove": cmd_index_remove,
    "index-rebuild": cmd_index_rebuild,
    "index-list": cmd_index_list,
    "list": cmd_list,
    "search": cmd_search,
    "show": cmd_show,
    "remove": cmd_remove,
    "stats": cmd_stats,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("FeedFwd Card CLI", file=sys.stderr)
        print(f"Commands: {', '.join(COMMANDS.keys())}", file=sys.stderr)
        print("\nUsage:", file=sys.stderr)
        print("  card_cli.py check-dup --name NAME --keywords KW1,KW2", file=sys.stderr)
        print("  card_cli.py count-tokens TEXT", file=sys.stderr)
        print("  card_cli.py index-add /path/to/card.md", file=sys.stderr)
        print("  card_cli.py index-remove CARD_NAME", file=sys.stderr)
        print("  card_cli.py index-rebuild", file=sys.stderr)
        print("  card_cli.py index-list", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    exit_code = COMMANDS[command](sys.argv[2:])
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
