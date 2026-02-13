#!/bin/bash
# FeedFwd Installer
# Clones the plugin, installs dependencies, and configures Claude Code.

set -e

INSTALL_DIR="$HOME/.claude/plugins/feedfwd"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "📡 FeedFwd Installer"
echo "===================="
echo ""

# 1. Clone or update
if [ -d "$INSTALL_DIR" ]; then
    echo "→ Updating existing installation..."
    git -C "$INSTALL_DIR" pull --quiet
else
    echo "→ Installing to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --quiet https://github.com/adityarbhat/feedfwd.git "$INSTALL_DIR"
fi

# 2. Install Python dependencies
echo "→ Installing Python dependencies..."
pip install --quiet httpx beautifulsoup4 python-frontmatter tiktoken 2>/dev/null || \
pip3 install --quiet httpx beautifulsoup4 python-frontmatter tiktoken 2>/dev/null || \
{ echo "⚠️  Could not install Python packages. Please run manually:"; \
  echo "   pip install httpx beautifulsoup4 python-frontmatter tiktoken"; }

# 3. Create knowledge base directory
echo "→ Setting up knowledge base..."
mkdir -p "$HOME/.config/feedfwd/knowledge"/{prompting,python,workflow,tools,testing,architecture,debugging}

# 4. Add to Claude Code settings
if [ -f "$SETTINGS_FILE" ]; then
    # Check if feedfwd is already in pluginDirs
    if grep -q "feedfwd" "$SETTINGS_FILE" 2>/dev/null; then
        echo "→ Already configured in Claude Code settings."
    else
        echo "→ Adding to Claude Code settings..."
        # Use python to safely modify JSON
        python3 -c "
import json, sys
try:
    with open('$SETTINGS_FILE', 'r') as f:
        settings = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    settings = {}

dirs = settings.get('pluginDirs', [])
if '$INSTALL_DIR' not in dirs:
    dirs.append('$INSTALL_DIR')
    settings['pluginDirs'] = dirs
    with open('$SETTINGS_FILE', 'w') as f:
        json.dump(settings, f, indent=2)
    print('   Added to pluginDirs in settings.json')
else:
    print('   Already in pluginDirs')
" 2>/dev/null || {
            echo "⚠️  Could not auto-configure. Add this to $SETTINGS_FILE manually:"
            echo "   \"pluginDirs\": [\"$INSTALL_DIR\"]"
        }
    fi
else
    echo "→ Creating Claude Code settings..."
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    echo "{\"pluginDirs\": [\"$INSTALL_DIR\"]}" | python3 -m json.tool > "$SETTINGS_FILE" 2>/dev/null || \
    echo "{\"pluginDirs\": [\"$INSTALL_DIR\"]}" > "$SETTINGS_FILE"
fi

echo ""
echo "✅ FeedFwd installed!"
echo ""
echo "Start a new Claude Code session and try:"
echo "   /learn https://example.com/great-article"
echo ""
echo "Plugin location: $INSTALL_DIR"
echo "Knowledge base:  ~/.config/feedfwd/knowledge/"
