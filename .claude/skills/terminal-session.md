# Terminal Session — Ad-Hoc Interactive Testing

Use this skill when you need to **observe or interact with** at-cmd's terminal behavior in real time — animations, spinners, TUI elements, inline editing, or anything that requires seeing the actual terminal output rather than just stdout after exit.

## How It Works

You use **tmux** to create a detached terminal session you can control, and **asciinema** inside it to record everything. This gives you:

- **Eyes**: `tmux capture-pane -p` snapshots the screen at any moment
- **Hands**: `tmux send-keys` types into the terminal
- **Memory**: The `.cast` file records every frame with timestamps for later analysis

## Protocol

### 1. Start a session

```bash
# Create a named tmux session with asciinema recording inside it
tmux new-session -d -s atcmd-test -x 120 -y 30 \
  "asciinema rec --overwrite --quiet --cols 120 --rows 30 -c bash /tmp/atcmd-session.cast"

# Wait for shell prompt
sleep 1
tmux capture-pane -t atcmd-test -p
```

### 2. Send commands

```bash
# Type a command
tmux send-keys -t atcmd-test 'at-cmd find large jpg files' Enter

# Wait a beat, then look
sleep 0.5
tmux capture-pane -t atcmd-test -p
```

### 3. Send special keys

```bash
# Tab
tmux send-keys -t atcmd-test Tab

# Ctrl-C
tmux send-keys -t atcmd-test C-c

# Alt-G (for inline mode hotkey)
tmux send-keys -t atcmd-test M-g

# Enter
tmux send-keys -t atcmd-test Enter

# Escape
tmux send-keys -t atcmd-test Escape

# Arrow keys
tmux send-keys -t atcmd-test Left
tmux send-keys -t atcmd-test Right
```

### 4. Capture multiple frames (for animations)

```bash
# Capture 10 frames at 200ms intervals to observe spinner/animation
for i in $(seq 1 10); do
  echo "=== Frame $i ==="
  tmux capture-pane -t atcmd-test -p
  sleep 0.2
done
```

### 5. Stop and analyze

```bash
# Exit the shell (ends asciinema recording)
tmux send-keys -t atcmd-test 'exit' Enter
sleep 1

# Kill the tmux session
tmux kill-session -t atcmd-test 2>/dev/null

# Parse the recording
python3 -c "
import sys; sys.path.insert(0, '.')
from tests.e2e.harness import CastRecording
from pathlib import Path
rec = CastRecording.load(Path('/tmp/atcmd-session.cast'))
print(f'Duration: {rec.frames[-1].timestamp:.1f}s')
print(f'Total frames: {len(rec.frames)}')
print()
print('--- stdout ---')
print(rec.stdout_text()[:2000])
"
```

### 6. Cleanup

```bash
tmux kill-session -t atcmd-test 2>/dev/null
rm -f /tmp/atcmd-session.cast
```

## Tips

- **Always capture-pane after sending keys** — you're blind otherwise
- **Use `sleep 0.3`** between send and capture for most commands; use `sleep 2-5` when waiting for LLM responses
- **Name sessions descriptively** (e.g., `atcmd-spinner`, `atcmd-tui`) so you don't collide with other sessions
- **The .cast file persists** after the session ends — you can replay it with `asciinema play /tmp/atcmd-session.cast` or parse it with the Python harness
- **For TUI testing** (Textual apps like `at-cmd config`), capture-pane is essential since the TUI redraws the entire screen
- **Multiple sessions**: you can run several tmux sessions in parallel to compare behaviors

## When to Use This vs E2E Tests

| Scenario | Use |
|---|---|
| Repeatable assertion about behavior | E2E test (`tests/e2e/`) |
| Exploring a new feature interactively | This skill |
| Debugging a visual glitch | This skill |
| Verifying animation timing | Either (this for exploration, e2e for regression) |
| CI pipeline | E2E tests only |
