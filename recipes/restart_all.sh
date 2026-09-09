#!/bin/sh
# Kill and cleanly relaunch every character's mind.py loop, consistently.
#
# Manually retyping `pkill` + `nohup ... &` per character was the single most
# repeated and error-prone action this project needed -- a missed character, a
# stale flag, a wrong log path. This is that whole sequence, once, for every
# character with a mind file.
#
#   sh recipes/restart_all.sh
#   sh recipes/restart_all.sh --patience 8      # extra flags forwarded to mind.py
#
# Logs go to $LOG_DIR/<character>_mind.log (default: ../recipes/logs/ beside
# this script -- override with LOG_DIR=/some/path).
#
# WHY THE KILL IS TWO-STEP. mind.py only checks its --stop-file *between*
# cycles, and while a cycle is running the work is happening in a child recipe
# process (travel.py, cast.py, shop.py, ...) holding the character. Signalling
# the parent alone leaves that child acting, and starting a fresh loop then
# puts TWO actors on one character -- which the world does not serialise for
# you, so their observations and actions interleave and corrupt each other.
# Observed live: two mind.py loops on one character, each with its own
# travel.py, walking it in opposite directions. So: signal, kill the parent,
# kill any child recipe still pinned to that character, then verify none
# remain before launching.

set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${LOG_DIR:-$HERE/logs}"
STOP_DIR="${STOP_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$LOG_DIR"

minds() {
  for mind in "$HERE"/minds/*.json; do
    name="$(basename "$mind" .json)"
    [ "$name" = "example" ] && continue
    printf '%s\n' "$name"
  done
}

# --- stop -------------------------------------------------------------------
for name in $(minds); do
  : > "$STOP_DIR/$name.stop"                       # ask for a graceful exit
  pkill -f "mind.py --character $name" 2>/dev/null || true
done
sleep 1
for name in $(minds); do
  # Any recipe still pinned to this character is a child of the loop we just
  # killed, and it is still holding the character. It has to go too.
  pkill -f "\.py --character $name" 2>/dev/null || true
  pkill -f "\.py .*--character $name" 2>/dev/null || true
done
sleep 1

# --- verify -----------------------------------------------------------------
stuck=""
for name in $(minds); do
  if pgrep -f "\-\-character $name" >/dev/null 2>&1; then stuck="$stuck $name"; fi
done
if [ -n "$stuck" ]; then
  echo "refusing to start: processes still holding:$stuck" >&2
  echo "inspect with: pgrep -fl -- --character" >&2
  exit 1
fi

# --- start ------------------------------------------------------------------
# Connect first. The world logs a character out after ~30 minutes without a
# call, so any character whose loop died a while ago is probably offline --
# and mind.py's first `state` then fails with "Character is not connected",
# which reads like a broken mind file rather than an idle timeout. Observed
# live. `connect` is harmless when it is already connected.
for name in $(minds); do
  python3 "$HERE/../clawscape.py" connect --character "$name" >/dev/null 2>&1 || true
done

for name in $(minds); do
  rm -f "$STOP_DIR/$name.stop"
  log="$LOG_DIR/${name}_mind.log"
  nohup python3 "$HERE/mind.py" --character "$name" --mind "$HERE/minds/$name.json" \
    --loop --max-cycles 0 --patience 6 --stop-file "$STOP_DIR/$name.stop" "$@" \
    > "$log" 2>&1 &
  disown 2>/dev/null || true
  echo "started $name (pid $!) -> $log   stop: touch $STOP_DIR/$name.stop"
done
