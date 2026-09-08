#!/usr/bin/env python3
"""Walk further than one `walkTo` call safely handles, and stop for a reason.

`walkTo` silently caps at roughly 7-8 tiles per call: a longer jump either
comes back `client_rejected`, or worse, comes back `success: true` while the
character never actually moves -- there is no reliable error to catch either
way. A Gate, Door or Stile blocking the path looks identical: the same
no-movement symptom, indistinguishable from the hop cap unless something
already suspects an obstacle and goes looking for one. Driving this a tick at
a time means paying for every hop in context and re-diagnosing the same two
problems by hand each trip.

This runs the walk as a script instead: it always hops in small steps, and
the moment a hop doesn't move the character, it looks for something to cross
before retrying -- a Gate or Door ("Open"), a Stile or Fence ("Climb-over"),
or a known dialog-gated border from --routes (see routes.json). If none of
those apply it tries a short sidestep, since a boundary that blocks straight-
line travel is often crossable a few tiles to either side even with no
interactable loc marking the way through.

    uv run recipes/travel.py --character gorruk --x 3222 --z 3218
    uv run recipes/travel.py --character gorruk --landmark lumbridge_courtyard

Output is one JSON object per round: a checkpoint per hop, then a final
`done` line naming why it stopped. Exit status is 0 on arrival, 2 when it
stopped for another reason, 1 on a usage or world error.

It does NOT solve every obstacle -- a river or wall with no interactable loc
and no sidestep opening within --probe-radius is a real unmapped crossing,
not something to keep retrying. When that happens it stops with reason
"stuck" and appends what it found to --routes' `open_problems`, so the next
run (or the next agent) sees it was already tried instead of re-discovering
the same dead end.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

CLI = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "clawscape.py")
)
DEFAULT_ROUTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "routes.json")


class Stop(Exception):
    """The walk is over; `reason` says why, in one machine-readable word."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def cli(character: str, *words: str) -> dict:
    """Run one CLI command and parse its JSON, whatever its exit status."""
    command = [sys.executable, CLI, *words, "--character", character]
    done = subprocess.run(command, capture_output=True, text=True)
    raw = done.stdout.strip() or done.stderr.strip()
    try:
        return json.loads(raw or "{}")
    except ValueError:
        raise Stop("cli_unreadable", raw[:400] or "no output")


def read_state(character: str) -> dict:
    result = cli(character, "state", "--full")
    state = result.get("state")
    if not isinstance(state, dict):
        raise Stop("no_state", json.dumps(result)[:400])
    return state


def act(character: str, kind: str, fields: dict) -> dict:
    return cli(character, "act", kind, "--json", json.dumps(fields))


def wait(character: str, ticks: int) -> dict:
    return cli(character, "wait", str(ticks))


def pos_of(state: dict) -> tuple:
    player = state.get("player") or {}
    return (player.get("worldX"), player.get("worldZ"))


def guard(state: dict, args) -> None:
    player = state.get("player") or {}
    if player.get("isDead"):
        raise Stop("died", "inventory is lost on death; re-equip before resuming")
    hp = player.get("hp")
    if isinstance(hp, int) and hp <= args.min_hp:
        raise Stop("low_hp", "hp %d at or under --min-hp %d" % (hp, args.min_hp))


def load_routes(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as handle:
            return json.load(handle)
    return {"landmarks": {}, "crossings": [], "confirmed_paths": [], "open_problems": []}


def save_routes(path: str, routes: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(routes, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def find_loc_crossing(state: dict, near_x: int, near_z: int, radius: int):
    """A Gate/Door ("Open") or Stile/Fence ("Climb-over") within radius tiles."""
    for loc in state.get("nearbyLocs") or []:
        options = loc.get("options") or []
        action = "Open" if "Open" in options else ("Climb-over" if "Climb-over" in options else None)
        if action and loc.get("name") in ("Gate", "Door", "Large door", "Stile", "Fence"):
            if abs(loc["x"] - near_x) <= radius and abs(loc["z"] - near_z) <= radius:
                entry = next(
                    (o for o in loc.get("optionsWithIndex") or [] if o.get("text") == action),
                    None,
                )
                if entry:
                    return loc, action, entry["opIndex"]
    return None


def find_known_crossing(routes: dict, pos: tuple):
    """A --routes crossing whose x_range/z_range trigger box contains pos.

    This is for crossings a loc-interact can't solve at all -- confirmed so
    far: a toll dialog with a border NPC, required before `walkTo` will even
    accept a step across the boundary, regardless of any Gate loc nearby.
    """
    for crossing in routes.get("crossings") or []:
        xlo, xhi = crossing["x_range"]
        zlo, zhi = crossing["z_range"]
        if xlo <= pos[0] <= xhi and zlo <= pos[1] <= zhi:
            return crossing
    return None


def cross_via_dialog(character: str, crossing: dict, target: tuple, log) -> bool:
    npc_name = crossing.get("npc")
    state = read_state(character)
    npc = next((n for n in state.get("nearbyNpcs") or [] if n.get("name") == npc_name), None)
    if not npc:
        return False
    act(character, "talkToNpc", {"npcIndex": npc["index"]})
    for _ in range(10):
        wait(character, 3)
        state = read_state(character)
        dialog = state.get("dialog") or {}
        if not dialog.get("isOpen"):
            break
        if not dialog.get("isWaiting"):
            options = dialog.get("options") or []
            index = options[0]["index"] if options else 1
            for option in options:
                text = str(option.get("text", "")).lower()
                if "ok" in text or "yes" in text:
                    index = option["index"]
            act(character, "clickDialogOption", {"optionIndex": index})
    beyond = crossing.get("beyond") or list(target)
    before = pos_of(read_state(character))
    act(character, "walkTo", {"x": beyond[0], "z": beyond[1]})
    for _ in range(5):
        wait(character, 4)
        if pos_of(read_state(character)) != before:
            break
    after = pos_of(read_state(character))
    log({"crossing": crossing.get("note", npc_name), "from": list(before), "to": list(after)})
    return after != before


def sidestep(character: str, cur: tuple, target: tuple, hop_size: int, probe_radius: int, log):
    """A few short perpendicular offsets, tried before giving up entirely.

    A boundary that blocks straight-line travel is usually crossable a short
    distance to either side even when nothing marks the way through -- the
    thing a person does by hand ("west opened up"). Perpendicular to the
    dominant travel axis, since that is the axis most likely still blocked.
    """
    dx, dz = target[0] - cur[0], target[1] - cur[1]
    offsets = [probe_radius, -probe_radius, probe_radius * 2, -probe_radius * 2]
    probes = (
        [(cur[0] + o, cur[1]) for o in offsets]
        if abs(dz) >= abs(dx)
        else [(cur[0], cur[1] + o) for o in offsets]
    )
    for probe_x, probe_z in probes:
        act(character, "walkTo", {"x": probe_x, "z": probe_z})
        for _ in range(4):
            wait(character, 4)
            state = read_state(character)
            new_pos = pos_of(state)
            if new_pos != cur:
                log({"sidestep": [probe_x, probe_z], "landed": list(new_pos)})
                return new_pos
    return None


def travel(args) -> str:
    character = args.character
    routes = load_routes(args.routes)
    if args.landmark:
        if args.landmark not in routes.get("landmarks", {}):
            raise Stop("unknown_landmark", "known: %s" % list(routes.get("landmarks", {})))
        target = tuple(routes["landmarks"][args.landmark])
    else:
        target = (args.x, args.z)

    state = read_state(character)
    start = pos_of(state)
    emit({"start": list(start), "target": list(target)})
    hops = []
    obstacles = []
    stuck_streak = 0

    for round_number in range(1, args.max_rounds + 1):
        guard(state, args)
        cur = pos_of(state)
        dx, dz = target[0] - cur[0], target[1] - cur[1]
        if abs(dx) <= 1 and abs(dz) <= 1:
            record(args.routes, routes, start, target, hops, obstacles, True)
            return "arrived"

        step = (cur[0] + clamp(dx, -args.hop_size, args.hop_size),
                cur[1] + clamp(dz, -args.hop_size, args.hop_size))
        act(character, "walkTo", {"x": step[0], "z": step[1]})
        for _ in range(5):
            wait(character, args.ticks)
            state = read_state(character)
            if pos_of(state) != cur:
                break
        new_pos = pos_of(state)
        emit({"round": round_number, "tick": state.get("tick"), "pos": list(new_pos),
              "hp": (state.get("player") or {}).get("hp")})

        if new_pos != cur:
            hops.append(new_pos)
            stuck_streak = 0
            continue

        crossed = False
        loc_crossing = find_loc_crossing(state, cur[0], cur[1], args.probe_radius)
        if loc_crossing:
            loc, action, op_index = loc_crossing
            act(character, "interactLoc",
                {"x": loc["x"], "z": loc["z"], "locId": loc["id"], "optionIndex": op_index})
            wait(character, 2)
            act(character, "walkTo", {"x": step[0], "z": step[1]})
            for _ in range(5):
                wait(character, args.ticks)
                if pos_of(read_state(character)) != cur:
                    break
            if pos_of(read_state(character)) != cur:
                obstacles.append({"pos": list(cur), "resolved_by": "%s:%s" % (loc["name"], action)})
                crossed = True

        if not crossed:
            known = find_known_crossing(routes, cur)
            if known:
                crossed = cross_via_dialog(character, known, target, emit)
                if crossed:
                    obstacles.append({"pos": list(cur), "resolved_by": "dialog:%s" % known.get("npc")})

        if not crossed:
            landed = sidestep(character, cur, target, args.hop_size, args.probe_radius, emit)
            if landed:
                hops.append(landed)
                obstacles.append({"pos": list(cur), "resolved_by": "sidestep", "landed": list(landed)})
                crossed = True

        if crossed:
            stuck_streak = 0
            state = read_state(character)
            continue

        stuck_streak += 1
        if stuck_streak >= args.patience:
            record(args.routes, routes, start, target, hops, obstacles, False, stuck_at=cur)
            raise Stop(
                "stuck",
                "no Gate/Door/Stile, no known --routes crossing, and no sidestep "
                "opening within %d tiles of %s; logged to open_problems in %s"
                % (args.probe_radius, cur, args.routes),
            )

    record(args.routes, routes, start, target, hops, obstacles, False, stuck_at=pos_of(state))
    return "max_rounds"


def record(path, routes, start, target, hops, obstacles, success, stuck_at=None) -> None:
    entry = {
        "from": list(start),
        "to": list(target),
        "hops": [list(h) for h in hops],
        "obstacles_crossed": obstacles,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if success:
        routes.setdefault("confirmed_paths", []).append(entry)
    else:
        entry["stuck_at"] = list(stuck_at) if stuck_at else None
        routes.setdefault("open_problems", []).append(entry)
    save_routes(path, routes)


def emit(row: dict) -> None:
    print(json.dumps(row, separators=(",", ":")), flush=True)


def parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk to a destination in safe hops, crossing what blocks the way."
    )
    parser.add_argument("--character", required=True)
    target = parser.add_argument_group("destination (one of)")
    target.add_argument("--landmark", help="A name from --routes' landmarks")
    target.add_argument("--x", type=int)
    target.add_argument("--z", type=int)
    parser.add_argument("--routes", default=DEFAULT_ROUTES, help="Path to routes.json")
    parser.add_argument("--hop-size", type=int, default=7, help="Tiles per walkTo call")
    parser.add_argument("--ticks", type=int, default=4, help="Ticks to wait per hop")
    parser.add_argument("--max-rounds", type=int, default=150)
    parser.add_argument("--patience", type=int, default=3, help="Stuck rounds to allow before stopping")
    parser.add_argument("--probe-radius", type=int, default=15,
                         help="Tiles to search for a crossing or sidestep opening")
    parser.add_argument("--min-hp", type=int, default=5, help="Stop at or under this")
    args = parser.parse_args(argv)
    if not args.landmark and (args.x is None or args.z is None):
        parser.error("give --landmark or both --x and --z")
    if args.landmark and (args.x is not None or args.z is not None):
        parser.error("--landmark and --x/--z are mutually exclusive")
    return args


def main(argv) -> int:
    args = parse(argv)
    try:
        outcome = travel(args)
    except Stop as stop:
        emit({"done": stop.reason, "detail": stop.detail})
        return 1 if stop.reason in ("cli_unreadable", "no_state", "unknown_landmark") else 2
    except KeyboardInterrupt:
        emit({"done": "interrupted", "detail": "the character keeps its last action"})
        return 2
    emit({"done": outcome})
    return 0 if outcome == "arrived" else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
