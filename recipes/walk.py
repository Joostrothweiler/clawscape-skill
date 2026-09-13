#!/usr/bin/env python3
"""Walk a list of waypoints, recording every hop into routes.json.

`travel.py` hops in small steps and probes for crossings, which is right for
getting past a known obstacle and wrong for covering open ground. This is the
other half: it sends one long `walkTo` per leg and lets the server path, which
is what `references/mechanics.md` says to do for travel.

Two things it does that a hand-rolled walker usually does not, both learned the
expensive way:

  - **It records.** Only hops written to routes.json feed `route.py`, the graph
    planner. An agent walked several hundred tiles with a private walker that
    logged nothing; `route.py` then answered `unmapped_destination` and the whole
    exploration was lost. Logging goes through travel.py's own `record()` /
    `update_routes()` so the file lock still spans load-and-save.
  - **It never reads position mid-walk.** `state` during a walk reports a tile
    the character is passing through, not where it stops. Deciding on those
    coordinates produces phantom "it went backwards" conclusions. `settled()`
    polls until two consecutive reads agree.

A leg that stops making progress is recorded to `open_problems` and the run ends
there, so a real wall is written down once rather than re-attempted.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atlas  # noqa: E402
from travel import record  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)
DEFAULT_ROUTES = os.path.join(HERE, "routes.json")


def cli(character, *args):
    r = subprocess.run(
        ["python3", "clawscape.py", "--character", character] + list(args),
        capture_output=True,
        text=True,
        cwd=CLI_DIR,
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def _reconnect(character):
    """A dropped session answers every action with success and moves nothing.

    Long unattended runs hit this constantly -- a whole expedition once executed
    against a dead session, reporting stalls the entire way and moving zero
    tiles. Reconnecting on a failed state read is the difference between a run
    that survives the day and one that quietly does nothing.
    """
    cli(character, "connect", "--character", character)


def state(character):
    for attempt in range(3):
        d = cli(character, "state", "--full").get("state")
        if d:
            return d
        if attempt == 0:
            _reconnect(character)
    raise SystemExit(json.dumps({"error": "no state; is the character connected?"}))


def settled(character, tries=6):
    """Position, read only once it stops changing between polls.

    Every settled read is also an observation: the atlas grows as a side effect
    of walking, so nobody has to remember to record anything.
    """
    last = None
    for _ in range(tries):
        d = state(character)
        p = (d["player"]["worldX"], d["player"]["worldZ"])
        if p == last:
            atlas.observe(d, stood=list(p))
            return p, d
        last = p
        cli(character, "wait", "3")
    d = state(character)
    atlas.observe(d, stood=list(last) if last else None)
    return last, d


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def eat(character, d, min_hp, food):
    if d["player"]["hp"] >= min_hp:
        return d
    have = [i for i in d["inventory"] if i["name"] == food]
    if not have:
        emit(warn="no food left", hp=d["player"]["hp"])
        return d
    cli(
        character,
        "act",
        "useInventoryItem",
        "--json",
        json.dumps({"slot": have[0]["slot"], "optionIndex": 1}),
    )
    cli(character, "wait", "3")
    return state(character)


def leg(character, target, min_hp, food, calls, tol, stall_limit=4):
    tx, tz = target
    hops = []
    here, _ = settled(character)
    best = abs(here[0] - tx) + abs(here[1] - tz)
    stalls = 0

    for _ in range(calls):
        eat(character, state(character), min_hp, food)
        here, _ = settled(character)
        if abs(here[0] - tx) <= tol and abs(here[1] - tz) <= tol:
            return True, hops, here
        cli(character, "act", "walkTo", "--json", json.dumps({"x": tx, "z": tz}))
        cli(character, "wait", "6")
        after, _ = settled(character)
        if after != here:
            hops.append(after)
        gap = abs(after[0] - tx) + abs(after[1] - tz)
        if gap < best:
            best, stalls = gap, 0
        else:
            stalls += 1
            if stalls >= stall_limit:
                # a leg that stopped closing is evidence about the next tile,
                # not proof: atlas only believes a block after repeats
                atlas.observe(
                    state(character),
                    stood=list(after),
                    refused=[tx, tz],
                    reason="leg stalled",
                )
                return False, hops, after
    final, _ = settled(character)
    return (abs(final[0] - tx) <= tol and abs(final[1] - tz) <= tol), hops, final


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument(
        "--waypoints",
        required=True,
        help="semicolon separated x,z pairs, walked in order",
    )
    ap.add_argument("--routes", default=DEFAULT_ROUTES)
    ap.add_argument(
        "--min-hp", type=int, default=0, help="eat below this; 0 disables eating"
    )
    ap.add_argument("--food", default="Lobster")
    ap.add_argument("--tol", type=int, default=3, help="tiles that count as arrived")
    ap.add_argument("--calls", type=int, default=40, help="walkTo calls per leg")
    a = ap.parse_args(argv)

    wps = []
    for chunk in a.waypoints.split(";"):
        x, z = chunk.split(",")
        wps.append((int(x.strip()), int(z.strip())))

    for wp in wps:
        start, _ = settled(a.character)
        ok, hops, end = leg(a.character, wp, a.min_hp, a.food, a.calls, a.tol)
        if hops or not ok:
            record(a.routes, start, wp, hops, [], ok, stuck_at=None if ok else end)
        emit(waypoint=list(wp), arrived=ok, at=list(end), hops_logged=len(hops))
        if not ok:
            break

    end, d = settled(a.character)
    emit(
        final=list(end),
        hp=d["player"]["hp"],
        food=sum(1 for i in d["inventory"] if i["name"] == a.food),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
