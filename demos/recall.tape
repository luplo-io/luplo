# demos/recall.tape
#
# Render:  vhs demos/recall.tape
# Output:  demos/output/recall.gif  (~15s)
#
# Prereq:  ./demos/reset-db.sh

Output demos/output/recall.gif

Require uv
Require lp

Set FontSize 15
Set FontFamily "JetBrains Mono,Menlo"
Set Width 1200
Set Height 600
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set PlaybackSpeed 1.0

Type 'export LUPLO_DB_URL=postgresql://localhost/luplo_demos' Enter
Sleep 500ms

Type 'export LUPLO_PROJECT=demos' Enter
Sleep 500ms

Type 'clear' Enter
Sleep 300ms

# The hook: ask a question a solo dev would actually ask three weeks later.
Type 'uv run lp items search "Postgres SQLite"' Enter
Sleep 3s

# Let the viewer read the match.
Sleep 2s

# Drill into the superseding decision.
Type 'uv run lp items show dec00047' Enter
Sleep 5s

# End on the point: rationale + supersedes chain visible.
Sleep 2s
