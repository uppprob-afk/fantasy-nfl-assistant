#!/bin/bash
# Double-click (macOS) to refresh your league data and open the dashboard.
# Works from a Desktop shortcut too. Needs uv: https://docs.astral.sh/uv/

here="$(dirname "$(readlink -f "$0")")"
cd "$here" || exit 1
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv isn't installed. Install it with:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
elif [ ! -f config.yaml ]; then
  echo "No config.yaml yet. Copy config.example.yaml to config.yaml and fill in your league."
else
  echo "Updating your fantasy dashboard (about 20 seconds)..."
  echo
  if uv run python -m nfl_assistant.run; then
    open site/index.html
  else
    echo
    echo "Something went wrong. The message above says what."
  fi
fi

echo
read -n 1 -s -r -p "Press any key to close this window."
