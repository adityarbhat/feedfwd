# /learn Command
# ================================================================
# FeedFwd: Capture knowledge from URLs, pasted text, or screenshots.
# This is the primary input mechanism for the plugin.
#
# How it works in Claude Code:
#   When a user types "/learn <args>", Claude Code reads this file
#   and follows the instructions below. The command definition IS
#   the prompt — Claude interprets and executes it directly.
#
#   The command fetches article content in the main session (quick),
#   then spawns a Task subagent for the distillation work (isolated
#   from the main context window).
# ================================================================

---
name: learn
description: "Capture knowledge from a URL, pasted text, or screenshot and distill it into a knowledge card"
arguments: "[url1] [url2] [url3] ... or --list"
---

You are handling the FeedFwd `/learn` command. The user wants to capture
knowledge and distill it into an actionable knowledge card.

## Step 1: Determine the Mode

Look at the arguments the user provided:

- **If `--list` was passed**: Tell the user to run `/knowledge` instead. Stop here.
- **If one or more URLs were provided** (strings starting with http:// or https://): URL mode. Go to Step 2.
- **If no arguments were provided**: Paste mode. Go to Step 2b.
- **If the argument is not a URL** (no http/https prefix): Treat it as pasted text. Go to Step 2b.

## Step 2: URL Mode — Fetch Article Content

For each URL provided, fetch the article text:

```bash
python scripts/fetch_url.py "<url>"
```

**If the fetch fails** (non-zero exit code), report the error to the user:
```
⚠️ Couldn't fetch <url> — it may be behind a paywall or require authentication.
   Paste the content directly instead: run /learn with no args.
```
Then skip this URL and continue with the next one (if batch).

**If the fetch succeeds**, save the output text and go to Step 3.

## Step 2b: Paste Mode

If no URL was provided, ask the user to paste the article text, screenshot, or
content they want to learn from. Once they provide it, use that as the article
content and go to Step 3.

## Step 3: Distill into a Knowledge Card

For each successfully fetched article, spawn a Task subagent to distill it.
Use `subagent_type: "general-purpose"` and pass the following prompt:

---

**IMPORTANT**: Include ALL of the following in the Task prompt:

1. The full distiller instructions (copied from below)
2. The article source URL (or "pasted-text" if paste mode)
3. The full article text

Here are the distiller instructions to include in the Task prompt:

```
You are the FeedFwd distiller. Convert this article into a knowledge card.

SOURCE: <url or "pasted-text">

ARTICLE TEXT:
<the fetched article text>

INSTRUCTIONS:
Follow these steps exactly:

1. Identify the ONE core actionable technique or insight in this article.

2. Check for duplicates — run:
   python scripts/card_cli.py check-dup --name "proposed-name" --keywords "kw1,kw2,kw3"
   If output is "DUPLICATE: <name>", stop and report it.

3. Draft these fields:
   - name: kebab-case identifier
   - category: one of prompting/python/workflow/tools/testing/architecture/debugging (or new)
   - keywords: 4-8 trigger words that signal relevance
   - file_patterns: glob patterns for relevant file types
   - task_types: 1-3 from architecture/debugging/refactoring/testing/documentation/code-review/implementation/optimization
   - injection_text: DIRECT INSTRUCTION to Claude. "When [situation], do [action]." Under 250 tokens. NOT a summary.
   - insight: 2-3 sentences for human reference
   - example: before/after showing the technique

4. Verify token count — run:
   python scripts/card_cli.py count-tokens "your injection text"
   Must be under 250. Shorten and recheck if over.

5. Write the card to ~/.config/feedfwd/knowledge/<category>/<name>.md using this exact format:
   ---
   name: <name>
   source: "<source>"
   captured: <today's date YYYY-MM-DD>
   category: <category>
   score: 0.50
   times_surfaced: 0
   times_useful: 0
   triggers:
     keywords:
       - keyword1
       - keyword2
     file_patterns:
       - "*.py"
     task_types:
       - implementation
   injection_tokens: <count>
   ---

   ## Insight

   <insight text>

   ## Injection Text

   <injection text>

   ## Example

   Before: <before>
   After: <after>

6. Update the index — run:
   python scripts/card_cli.py index-add ~/.config/feedfwd/knowledge/<category>/<name>.md

7. Report the result in this exact format:
   RESULT: ✅ <name> → <category>/<name>.md (<tokens> injection tokens)
   or if duplicate:
   RESULT: ⚠️ Skipped: Similar to existing card '<existing-name>'

RULES:
- ONE technique per card. Pick the single most actionable insight.
- Injection Text is an INSTRUCTION, not a summary. "When..." or imperative verb.
- Never ask follow-up questions. Use your best judgment.
- If too vague or not actionable, set score to 0.30 instead of 0.50.
```

---

## Step 4: Report Results

**For a single URL**, show the Task subagent's result directly:
```
✅ Learned: <name> → <category>/<name>.md
```

**For batch URLs** (multiple URLs), collect all results and show a summary:
```
📚 Batch learn complete:
   ✅ <name1> → <category1>/
   ✅ <name2> → <category2>/
   ⚠️ Skipped: <url3> (similar to '<existing-name>')
   ❌ Failed: <url4> (could not fetch)
 N URLs processed, X learned, Y skipped, Z failed
```

**For paste mode**, show the result after distillation:
```
✅ Learned: <name> → <category>/<name>.md
```

## Important Notes

- Process batch URLs **sequentially** (one at a time), not in parallel.
- If ALL URLs fail to fetch, suggest paste mode as a fallback.
- Never ask the user to pick a category, name, or keywords — the distiller handles all of that automatically.
- The distiller Task subagent runs in isolation, so it won't pollute the main conversation context.
