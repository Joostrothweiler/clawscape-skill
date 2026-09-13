#!/usr/bin/env python3
"""Walk inside buildings and on upper floors, one verified tile at a time.

Outdoors, `trek.py` hands long legs to `walkTo` and lets the server path. That
is the right trade in open country and it fails completely indoors, for two
reasons that took a while to separate:

  - **`walkTo` does its own pathing and does not consult your plan.** Given a
    tile 20 away inside a building it usually refuses outright. Given a tile
    your plan says is adjacent it may route some other way and land somewhere
    else, which silently desynchronises the walk from the plan. Following a
    planned path by firing `walkTo` at each tile in turn deviates and then
    walks nonsense -- observed twice in one session, 22 tiles of planning
    wasted each time, the character ending at the wrong square with no error.
  - **Tile-level blocking cannot describe a building.** A wall sits on a tile
    *edge*. A character was refused a ladder **one tile west** because the LOC
    row on her own tile was a timberwall of shape 0 rotation 0 -- a wall on her
    west edge. Both tiles are perfectly standable.

So this plans over `mapdata.wall_edges()` and `solid_tiles()` for a specific
level, then takes **single steps and verifies each one landed on the intended
tile**, replanning from wherever it actually is the moment it did not. A step
that fails is recorded, so the next plan is a different plan.

Interacting with something is part of the job, because indoors the whole point
is usually a ladder or a chest. A ladder or staircase tile is **solid** (shape
10) -- a character never stands on it. It stands on an adjacent tile with no
wall on the shared edge, and `--use` walks to such a tile and interacts:

    python3 recipes/indoor.py --character arete --to 2617,3324
    python3 recipes/indoor.py --character arete --use 1747,2617,3323 --option 1

`--use` takes `locId,x,z`. It picks the approach tile for you rather than
trusting `reachable`, which is unreliable in both directions: false for a bank
booth that then opened fine, true for things that answered "I can't reach that!".
"""

import argparse
import json
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atlas  # noqa: E402
import mapdata  # noqa: E402
import walk  # noqa: E402

STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def obstacles(box, level, content):
    """Edges, solid tiles and terrain for one level, as a single view."""
    edges = mapdata.wall_edges(box[0], box[1], box[2], box[3], level, content)
    solid = mapdata.solid_tiles(box[0], box[1], box[2], box[3], level, content)
    terrain = set()
    if level == 0:
        terrain = mapdata.terrain_blocked(box[0], box[1], box[2], box[3], content)
    return edges, solid | terrain


def plan(start, goal, edges, blocked, box):
    """BFS where a move is refused by a blocked EDGE as well as a blocked tile."""
    blocked = set(blocked) - {start, goal}
    q = deque([start])
    came = {start: None}
    while q:
        cur = q.popleft()
        if cur == goal:
            path, n = [], cur
            while n:
                path.append(n)
                n = came[n]
            return path[::-1]
        x, z = cur
        for dx, dz in STEPS:
            nxt = (x + dx, z + dz)
            if nxt in came or nxt in blocked:
                continue
            if not (box[0] <= nxt[0] <= box[1] and box[2] <= nxt[1] <= box[3]):
                continue
            if (cur, nxt) in edges:
                continue
            came[nxt] = cur
            q.append(nxt)
    return None


def approach_tiles(loc, edges, blocked):
    """Tiles a loc can be used from: adjacent, standable, no wall between."""
    out = []
    for dx, dz in STEPS:
        t = (loc[0] + dx, loc[1] + dz)
        if t in blocked:
            continue
        if (t, loc) in edges:
            continue
        out.append(t)
    return out


def walk_verified(character, path, learned, box, level):
    """Single steps, each one checked. Returns (arrived, where, refused_edge)."""
    here = path[0]
    for want in path[1:]:
        walk.cli(
            character,
            "act",
            "walkTo",
            "--json",
            json.dumps({"x": want[0], "z": want[1]}),
        )
        walk.cli(character, "wait", "2")
        at, d = walk.settled(character)
        if at == want:
            here = at
            continue
        # It did not land where the plan said. Record the edge and stop; the
        # caller replans from where the character actually is, which is the
        # whole difference between this and firing walkTo down a list.
        learned.add((here, want))
        learned.add((want, here))
        atlas.observe(
            d, stood=list(at), refused=list(want), reason="indoor step refused"
        )
        return False, at, (here, want)
    return True, here, None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--to", help="x,z")
    ap.add_argument("--use", help="locId,x,z to walk to and interact with")
    ap.add_argument("--option", type=int, default=1)
    ap.add_argument("--content", default=None)
    ap.add_argument("--level", type=int, default=None, help="default: read it live")
    ap.add_argument("--margin", type=int, default=40)
    ap.add_argument("--replans", type=int, default=12)
    a = ap.parse_args(argv)

    if not a.to and not a.use:
        raise SystemExit(json.dumps({"error": "pass --to or --use"}))

    here, d = walk.settled(a.character)
    level = a.level if a.level is not None else (d.get("player") or {}).get("level", 0)

    loc = None
    if a.use:
        lid, lx, lz = (int(v) for v in a.use.split(","))
        loc = (lx, lz)
        goals = None
    else:
        gx, gz = (int(v) for v in a.to.split(","))
        goals = [(gx, gz)]

    learned = set()
    for attempt in range(a.replans):
        here, _ = walk.settled(a.character)
        box = (
            min(here[0], (loc or goals[0])[0]) - a.margin,
            max(here[0], (loc or goals[0])[0]) + a.margin,
            min(here[1], (loc or goals[0])[1]) - a.margin,
            max(here[1], (loc or goals[0])[1]) + a.margin,
        )
        edges, blocked = obstacles(box, level, a.content)
        edges = edges | learned

        if loc is not None:
            goals = approach_tiles(loc, edges, blocked)
            if not goals:
                emit(use=a.use, error="no approach tile without a wall between")
                return 1
            emit(approach_tiles=[list(g) for g in goals])

        best = None
        for g in goals:
            if g == here:
                best = [here]
                break
            p = plan(here, g, edges, blocked, box)
            if p and (best is None or len(p) < len(best)):
                best = p
        if not best:
            emit(at=list(here), error="no indoor route", level=level, attempt=attempt)
            return 1

        emit(plan=len(best), at=list(here), to=list(best[-1]), level=level)
        ok, at, refused = walk_verified(a.character, best, learned, box, level)
        if ok:
            emit(arrived=list(at), level=level)
            break
        emit(step_refused=list(refused[1]), at=list(at), replanning=attempt + 1)
    else:
        emit(error="out of replans")
        return 1

    if loc is None:
        return 0

    lid = int(a.use.split(",")[0])
    walk.cli(
        a.character,
        "act",
        "interactLoc",
        "--json",
        json.dumps({"locId": lid, "x": loc[0], "z": loc[1], "optionIndex": a.option}),
    )
    walk.cli(a.character, "wait", "5")
    at, d = walk.settled(a.character)
    msgs = [m.get("text") for m in (d.get("gameMessages") or [])[-2:]]
    emit(
        used=a.use,
        at=list(at),
        level=(d.get("player") or {}).get("level"),
        messages=msgs,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
