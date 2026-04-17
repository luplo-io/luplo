# demos/impact.tape
#
# Render:  vhs demos/impact.tape
# Output:  demos/output/impact.gif  (~30s)
#
# Prereq:  ./demos/reset-db.sh

Output demos/output/impact.gif

Require uv
Require lp

Set FontSize 15
Set FontFamily "JetBrains Mono,Menlo"
Set Width 1200
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set PlaybackSpeed 1.0

Type 'export LUPLO_DB_URL=postgresql://localhost/luplo_demos' Enter
Sleep 500ms

Type 'export LUPLO_PROJECT=demos' Enter
Sleep 500ms

Type 'clear' Enter
Sleep 300ms

# Set up the question: "what depends on this?" before running the command.
Type '# dec00023 is the WebSocket-over-gRPC call. What else depends on it?' Enter
Sleep 2s

Type 'uv run lp impact dec00023 --depth 3' Enter
Sleep 5s

# Let the tree render + read.
Sleep 3s

# Repeat with depth 1 to show the ceiling is configurable (but capped).
Type 'uv run lp impact dec00023 --depth 1' Enter
Sleep 4s

# The JSON shape an LLM would actually cite.
Type 'uv run lp impact dec00023 --format json | head -20' Enter
Sleep 5s

Sleep 2s
