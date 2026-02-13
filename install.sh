#!/bin/bash
# FeedFwd Installer
# ==================
# Clones the plugin, installs dependencies, and wires everything into
# Claude Code so /learn and /knowledge work in every session.
#
# How it works:
#   1. Clones the repo to ~/.claude/plugins/feedfwd/ (scripts + skills live here)
#   2. Copies commands to ~/.claude/commands/ (where Claude Code discovers them)
#   3. Rewrites relative script paths to absolute paths in the copied commands
#   4. Merges hooks into ~/.claude/settings.json (SessionStart + Stop)
#   5. Installs Python dependencies
#   6. Creates the knowledge base directory structure

set -e

INSTALL_DIR="$HOME/.claude/plugins/feedfwd"
COMMANDS_DIR="$HOME/.claude/commands"
SETTINGS_FILE="$HOME/.claude/settings.json"
SCRIPTS_DIR="$INSTALL_DIR/scripts"

echo "📡 FeedFwd Installer"
echo "===================="
echo ""

# 1. Clone or update the plugin source
if [ -d "$INSTALL_DIR" ]; then
    echo "→ Updating existing installation..."
    git -C "$INSTALL_DIR" pull --quiet
else
    echo "→ Cloning to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --quiet https://github.com/adityarbhat/feedfwd.git "$INSTALL_DIR"
fi

# 2. Install Python dependencies
echo "→ Installing Python dependencies..."
pip install --quiet httpx beautifulsoup4 python-frontmatter tiktoken 2>/dev/null || \
pip3 install --quiet httpx beautifulsoup4 python-frontmatter tiktoken 2>/dev/null || \
{ echo "⚠️  Could not install Python packages. Please run manually:"; \
  echo "   pip install httpx beautifulsoup4 python-frontmatter tiktoken"; }

# 3. Create knowledge base directory structure
echo "→ Setting up knowledge base..."
mkdir -p "$HOME/.config/feedfwd/knowledge"/{prompting,python,workflow,tools,testing,architecture,debugging}

# 4. Install commands (with path rewriting)
echo "→ Installing commands..."
mkdir -p "$COMMANDS_DIR"

# Copy learn.md and knowledge.md, replacing relative script paths with absolute ones
for cmd_file in "$INSTALL_DIR/commands"/*.md; do
    filename=$(basename "$cmd_file")
    # Replace 'scripts/' with absolute path, and '$PLUGIN_DIR/scripts/' too
    sed -e "s|scripts/|$SCRIPTS_DIR/|g" \
        -e "s|\\\$PLUGIN_DIR/scripts/|$SCRIPTS_DIR/|g" \
        "$cmd_file" > "$COMMANDS_DIR/$filename"
done

# 5. Install agent (distiller) — rewrite paths
echo "→ Installing agents..."
mkdir -p "$HOME/.claude/agents"
for agent_file in "$INSTALL_DIR/agents"/*.md; do
    filename=$(basename "$agent_file")
    sed -e "s|scripts/|$SCRIPTS_DIR/|g" \
        -e "s|\\\$PLUGIN_DIR/scripts/|$SCRIPTS_DIR/|g" \
        "$agent_file" > "$HOME/.claude/agents/$filename"
done

# 6. Install skills
echo "→ Installing skills..."
if [ -d "$INSTALL_DIR/skills" ]; then
    mkdir -p "$HOME/.claude/skills"
    cp -r "$INSTALL_DIR/skills"/* "$HOME/.claude/skills/" 2>/dev/null || true
fi

# 7. Add hooks to Claude Code settings
echo "→ Configuring hooks..."
python3 << 'PYTHON_SCRIPT'
import json, os

settings_file = os.path.expanduser("~/.claude/settings.json")
scripts_dir = os.path.expanduser("~/.claude/plugins/feedfwd/scripts")

# Load existing settings
try:
    with open(settings_file, "r") as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

# Ensure hooks dict exists
if "hooks" not in settings:
    settings["hooks"] = {}

# SessionStart hook — inject relevant knowledge cards
session_start_hook = {
    "hooks": [{
        "type": "command",
        "command": f"python {scripts_dir}/inject.py",
        "timeout": 5,
        "statusMessage": "FeedFwd: loading knowledge cards..."
    }]
}

# Stop hook — collect feedback on injected cards
stop_hook = {
    "hooks": [{
        "type": "command",
        "command": f"python {scripts_dir}/feedback.py",
        "timeout": 10,
        "statusMessage": "FeedFwd: updating card scores..."
    }]
}

# Add hooks (avoid duplicates by checking for feedfwd in existing commands)
def has_feedfwd_hook(hook_list):
    for group in hook_list:
        for hook in group.get("hooks", []):
            if "feedfwd" in hook.get("command", "").lower():
                return True
    return False

if "SessionStart" not in settings["hooks"]:
    settings["hooks"]["SessionStart"] = []
if not has_feedfwd_hook(settings["hooks"]["SessionStart"]):
    settings["hooks"]["SessionStart"].append(session_start_hook)

if "Stop" not in settings["hooks"]:
    settings["hooks"]["Stop"] = []
if not has_feedfwd_hook(settings["hooks"]["Stop"]):
    settings["hooks"]["Stop"].append(stop_hook)

# Write back
with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2)

print("   Hooks configured in settings.json")
PYTHON_SCRIPT

echo ""
echo "✅ FeedFwd installed!"
echo ""
echo "Start a new Claude Code session and try:"
echo "   /learn https://example.com/great-article"
echo ""
echo "Installed to:"
echo "   Scripts:        $INSTALL_DIR/scripts/"
echo "   Commands:       $COMMANDS_DIR/learn.md, knowledge.md"
echo "   Knowledge base: ~/.config/feedfwd/knowledge/"
echo ""
echo "To update later, re-run this installer."
