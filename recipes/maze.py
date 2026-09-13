#!/usr/bin/env python3
"""Cross terrain that is a field of obstacles rather than a wall, and learn it.

The Lava Maze is the case this was written for. It is not a barrier with a gap;
it is scattered lava tiles with walkable ground between them. `walkTo` will not
route through lava and a 20-tile hop skips over the gaps, so every long-range
attempt reports a stall and the whole region reads as impassable. It is not.

What works is a tile-level plan followed in short steps. Two pieces:

  - **Plan over the map data.** `mapdata.blocked()` gives the tiles carrying
    lava/wall/railing/fence locs, and a BFS over what is left produces a
    candidate path.
  - **Learn what the map data missed.** That data over-reports open ground:
    unmapped rock is not a loc, so some planned tiles are refused live. Naively
    re-running the plan is useless -- it produces the identical path and stalls
    on the identical tile, which is exactly what happened. So every tile that
    fails live is written to a persistent learned-blocked set and the path is
    replanned around it. That converges instead of looping.

The learned set is kept between runs, so a region gets cheaper each time it is
walked. Crossing the Lava Maze took ~100 learned tiles; the return trip through
the same ground was far quicker.

This does not record to routes.json -- use `walk.py` for ordinary travel, which
does. This is for the stretch where ordinary travel has already failed.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import atlas  # noqa: E402
import mapdata  # noqa: E402

DEFAULT_LEARNED = os.path.join(HERE, "blocked_tiles.json")


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


def state(character):
    for _ in range(3):
        d = cli(character, "state", "--full").get("state")
        if d:
            return d
    raise SystemExit(json.dumps({"error": "no state; is the character connected?"}))


def settled(character, tries=6):
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


def load_learned(path):
    try:
        return {tuple(t) for t in json.load(open(path))}
    except Exception:
        return set()


def save_learned(path, tiles):
    json.dump(sorted(list(t) for t in tiles), open(path, "w"))


def plan(start, goal, blocked, box):
    """BFS over tiles carrying no known blocker."""
    x_lo, x_hi, z_lo, z_hi = box
    blocked = set(blocked) - {start, goal}
    q = deque([start])
    came = {start: None}
    while q:
        cur = q.popleft()
        if cur == goal:
            path, node = [], cur
            while node:
                path.append(node)
                node = came[node]
            return path[::-1]
        x, z = cur
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (x + dx, z + dz)
            if nxt in came or nxt in blocked:
                continue
            if not (x_lo <= nxt[0] <= x_hi and z_lo <= nxt[1] <= z_hi):
                continue
            came[nxt] = cur
            q.append(nxt)
    return None


def eat(character, d, min_hp, food):
    if d["player"]["hp"] >= min_hp:
        return
    have = [i for i in d["inventory"] if i["name"] == food]
    if have:
        cli(
            character,
            "act",
            "useInventoryItem",
            "--json",
            json.dumps({"slot": have[0]["slot"], "optionIndex": 1}),
        )
        cli(character, "wait", "3")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--to", required=True, help="x,z")
    ap.add_argument("--content", default=None, help="path to the Content clone")
    ap.add_argument("--learned", default=DEFAULT_LEARNED)
    ap.add_argument(
        "--pad", type=int, default=45, help="tiles of margin around the start/goal box"
    )
    ap.add_argument("--min-hp", type=int, default=0)
    ap.add_argument("--food", default="Lobster")
    ap.add_argument("--replans", type=int, default=80)
    a = ap.parse_args(argv)

    gx, gz = (int(v) for v in a.to.split(","))
    goal = (gx, gz)
    learned = load_learned(a.learned)

    start, _ = settled(a.character)
    box = (
        min(start[0], gx) - a.pad,
        max(start[0], gx) + a.pad,
        min(start[1], gz) - a.pad,
        max(start[1], gz) + a.pad,
    )
    static = mapdata.blocked(box[0], box[1], box[2], box[3], a.content)
    emit(
        start=list(start),
        goal=list(goal),
        map_blocked=len(static),
        learned_blocked=len(learned),
    )

    for _ in range(a.replans):
        here, d = settled(a.character)
        if abs(here[0] - gx) + abs(here[1] - gz) <= 2:
            emit(arrived=list(here))
            break
        path = plan(here, goal, static | learned, box)
        if not path:
            emit(no_path=True, at=list(here), learned=len(learned))
            break

        for wp in path[1:]:
            before, d = settled(a.character)
            eat(a.character, d, a.min_hp, a.food)
            cli(
                a.character,
                "act",
                "walkTo",
                "--json",
                json.dumps({"x": wp[0], "z": wp[1]}),
            )
            cli(a.character, "wait", "4")
            after, _ = settled(a.character)
            if after == before:
                learned.add(wp)
                save_learned(a.learned, learned)
                atlas.observe(
                    state(a.character),
                    stood=list(after),
                    refused=list(wp),
                    reason="refused adjacent step",
                )
                emit(blocked=list(wp), at=list(after), learned=len(learned))
                break
            if abs(after[0] - gx) + abs(after[1] - gz) <= 2:
                break

    here, d = settled(a.character)
    emit(
        final=list(here),
        hp=d["player"]["hp"],
        remaining=abs(here[0] - gx) + abs(here[1] - gz),
        learned_blocked=len(learned),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
