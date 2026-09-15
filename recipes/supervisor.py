#!/usr/bin/env python3
"""Keep every character working, by restarting the work when it stops.

`keepalive.py` guarantees a character stays *connected*. Nothing guaranteed it
stays *busy*, and those are different failures with the same appearance: a
character standing still, online, healthy, achieving nothing.

It happened repeatedly. A trek gives up and exits; a harvest finishes its round
budget; a hunt stops because the food ran out. Each exit is correct and each
leaves the character idle until a human notices. On 2026-09-14 three characters
sat idle at once and it took Mike saying "it seems like you're stuck" -- the
second time that day he had to be the monitor.

So this is the monitor. It reads an assignment file mapping each character to
the command that is its job, checks whether that job is actually running, and
restarts it when it is not. The assignment is the intent; the process is the
evidence; a gap between them is the bug.

    python3 recipes/supervisor.py --assignments assignments.json

    {
      "arete":  ["recipes/hunt.py", "--character", "arete", "--npc", "Moss giant"],
      "scout1": ["recipes/trek.py", "--character", "scout1", "--to", "2614,3315"]
    }

**One actor per character, always.** `restart_all.sh` documents why: two loops
on one character walk it in opposite directions and corrupt each other's
observations. So before starting anything this kills whatever else holds that
character, and it never starts a second copy of a job that is already running.

Stop it by deleting the assignment file or touching the stop file.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)


def emit(**kw):
    kw["t"] = time.strftime("%H:%M:%S")
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def running_for(character):
    """PIDs of recipe processes currently holding this character."""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "recipes/.*--character %s" % character],
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        return []
    return [p for p in out.split() if p.strip()]


def kill_for(character, keep=()):
    for pid in running_for(character):
        if pid in keep:
            continue
        try:
            subprocess.run(["kill", "-9", pid], capture_output=True)
        except Exception:
            pass


def position(character):
    """Where the character is, or None if it cannot be read."""
    try:
        r = subprocess.run(
            ["python3", "clawscape.py", "--character", character, "state", "--full"],
            capture_output=True,
            text=True,
            cwd=CLI_DIR,
        )
        p = (json.loads(r.stdout).get("state") or {}).get("player") or {}
        if "worldX" in p:
            return (p["worldX"], p["worldZ"])
    except Exception:
        pass
    return None


def start(character, argv, logdir):
    """Launch one job, detached, with its own log."""
    os.makedirs(logdir, exist_ok=True)
    log = os.path.join(logdir, "%s.log" % character)
    cmd = [sys.executable] + list(argv)
    with open(log, "a") as fh:
        fh.write("\n=== supervisor start %s ===\n" % time.strftime("%H:%M:%S"))
        fh.flush()
        subprocess.Popen(
            cmd,
            cwd=CLI_DIR,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    emit(started=character, cmd=" ".join(argv[:4]), log=log)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--assignments", required=True)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--logdir", default=os.path.join(CLI_DIR, "logs"))
    ap.add_argument("--stop-file", default="/tmp/supervisor.stop")
    ap.add_argument(
        "--stall-checks",
        type=int,
        default=3,
        help="consecutive checks at the same tile before restarting the job",
    )
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)

    last_seen = {}
    stalled = {}
    emit(supervisor="start", assignments=a.assignments, interval=a.interval)
    while True:
        if os.path.exists(a.stop_file):
            emit(supervisor="stopping", reason="stop file present")
            return 0
        try:
            plan = json.load(open(a.assignments))
        except Exception as exc:
            emit(warn="cannot read assignments", detail=str(exc)[:90])
            plan = {}

        for character, cmd in plan.items():
            if not cmd:
                continue
            pids = running_for(character)
            if pids:
                # A live process is not progress. A trek that replans forever
                # from one tile, or walks a plan that leads away from the goal,
                # looks exactly like one that is working: the job is up, the log
                # ticks, and the character does not move. Two scouts did this
                # for an hour while the supervisor reported them healthy.
                #
                # So the check is the position, not the process.
                here = position(character)
                was = last_seen.get(character)
                last_seen[character] = here
                if here is not None and here == was:
                    stalled[character] = stalled.get(character, 0) + 1
                    if stalled[character] >= a.stall_checks:
                        emit(
                            stalled=character,
                            at=list(here),
                            checks=stalled[character],
                            note="alive but not moving, restarting",
                        )
                        kill_for(character)
                        stalled[character] = 0
                        try:
                            start(character, cmd, a.logdir)
                        except Exception as exc:
                            emit(warn="restart failed", detail=str(exc)[:80])
                    continue
                stalled[character] = 0
                continue
            # Idle. Clear any stragglers first so exactly one actor starts.
            kill_for(character)
            emit(idle=character, note="no job running, restarting assignment")
            try:
                start(character, cmd, a.logdir)
            except Exception as exc:
                emit(warn="could not start", character=character, detail=str(exc)[:90])

        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
