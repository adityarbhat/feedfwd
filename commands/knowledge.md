# /knowledge Command
# ================================================================
# FeedFwd: Browse, search, and manage the knowledge base.
#
# How it works in Claude Code:
#   When a user types "/knowledge [subcommand]", Claude Code reads
#   this file and follows the instructions. The heavy lifting is
#   done by card_cli.py — this command just runs it and formats
#   the output nicely for the user.
# ================================================================

---
name: knowledge
description: "Browse, search, and manage your FeedFwd knowledge base"
arguments: "[subcommand] [args]"
---

You are handling the FeedFwd `/knowledge` command. This provides a
management interface to the user's knowledge base.

## Step 1: Determine the Subcommand

Look at the arguments the user provided:

| User types | Subcommand | Action |
|------------|-----------|--------|
| `/knowledge` | **list** | Show all cards grouped by category |
| `/knowledge search <term>` | **search** | Search across cards |
| `/knowledge show <name>` | **show** | Display a card's full content |
| `/knowledge edit <name>` | **edit** | Help user edit a card |
| `/knowledge remove <name>` | **remove** | Delete a card |
| `/knowledge stats` | **stats** | Show knowledge base statistics |

## Subcommand: list (default)

Run this command and show the output directly to the user:

```bash
python scripts/card_cli.py list
```

The output is already formatted — just pass it through.

## Subcommand: search

Run this command with the user's search term:

```bash
python scripts/card_cli.py search "<term>"
```

Show the results. If matches are found, ask if the user wants to see
the full content of any card (offer to run `show`).

## Subcommand: show

Run this command with the card name:

```bash
python scripts/card_cli.py show "<name>"
```

Show the full output to the user. The output includes the card's
insight, injection text, example, metadata, and file path.

## Subcommand: edit

For editing a card, there are two approaches:

**Option A — Direct file edit**: Tell the user the file path so they
can open it in their editor:
```bash
python scripts/card_cli.py show "<name>"
```
The output includes the file path at the bottom. Point the user to it.

**Option B — Guided edit**: If the user describes what they want to
change (e.g., "update the injection text", "add a keyword"), read the
card file, make the edit using the Edit tool, and then re-index:
```bash
python scripts/card_cli.py index-add <path-to-card.md>
```

Ask the user which approach they prefer, or if they describe the change
inline, go with Option B.

## Subcommand: remove

**Ask for confirmation first.** Show the card name and ask:
"Remove card '<name>' from the knowledge base? This deletes the .md file."

If confirmed, run:

```bash
python scripts/card_cli.py remove "<name>"
```

## Subcommand: stats

Run this command and show the output:

```bash
python scripts/card_cli.py stats
```

If there are low performers listed, you can suggest the user consider
removing them with `/knowledge remove <name>`.

## Notes

- If the user provides a name that doesn't exist, the CLI will suggest
  similar names. Pass that suggestion through to the user.
- All card data lives in `~/.config/feedfwd/knowledge/`. The user can
  also browse and edit cards directly in their editor.
- After any edit or remove, the index is automatically updated.
