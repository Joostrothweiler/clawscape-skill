#!/usr/bin/env python3
"""Cross a long distance into ground nobody has mapped, cheapest method first.

Three recipes already cover pieces of travel and none of them covers a journey:

  - `route.py` plans over ground that has already been walked. It answers
    `no_known_route` for anywhere new, which is precisely where a scout goes.
  - `walk.py` sends one long `walkTo` and lets the server path. Fast and right
    for open ground, but it gives up at the first real obstacle and ends the run.
  - `maze.py` steps tile by tile around obstacles. It gets through almost
    anything and it is *slow* -- a scout sent 600 tiles west on maze.py alone
    covered 29 tiles in the time a `walkTo` would have covered several hundred.

So a long trip currently means choosing in advance between "fast but stops at
the first fence" and "gets there tomorrow". This picks per obstacle instead:
stride toward the goal with `walk.py`'s leg, and the moment a leg stops closing
the distance, hand just that obstacle to `maze.py` with a small detour budget,
then go back to striding.

That ordering is the whole idea. Most of a journey is open ground, so most of it
should cost one `walkTo`; the expensive method should be spent only on the few
tiles that actually need it.

Everything is recorded on the way through, because both underlying recipes
already record: `walk.py`'s leg writes hops to routes.json, and every settled
read feeds the atlas. A scout that walks without recording teaches nobody, which
has happened here before and cost several hundred tiles of exploration.

Usage:
    python3 recipes/trek.py --character scout2 --to 2670,3312 --content ../Content

A trek that cannot close the last gap stops and says where, with the obstacle
written to routes.json as an open problem, rather than looping.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atlas  # noqa: E402
import walk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def step_toward(here, goal, stride):
    """A waypoint `stride` tiles along the straight line from here to goal.

    Deliberately naive: the server paths around whatever is in the way, and a
    clever client-side line would just be a second, worse pathfinder.
    """
    hx, hz = here
    gx, gz = goal
    dx, dz = gx - hx, gz - hz
    span = max(abs(dx), abs(dz))
    if span <= stride:
        return (gx, gz)
    return (hx + round(dx * stride / span), hz + round(dz * stride / span))


def detour(character, goal, content, budget, min_hp):
    """Hand one obstacle to maze.py, with a bounded budget.

    maze.py is the expensive tool, so it is given a near target rather than the
    whole journey: get *past this fence*, not *go to Ardougne*.
    """
    r = subprocess.run(
        [
            "python3",
            os.path.join(HERE, "maze.py"),
            "--character",
            character,
            "--to",
            "%d,%d" % goal,
            "--pad",
            str(budget),
            "--min-hp",
            str(min_hp),
        ]
        + (["--content", content] if content else []),
        capture_output=True,
        text=True,
        cwd=CLI_DIR,
    )
    last = {}
    for line in (r.stdout or "").splitlines():
        try:
            last = json.loads(line)
        except Exception:
            continue
    return last


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--to", required=True, help="x,z")
    ap.add_argument("--content", default=None)
    ap.add_argument("--stride", type=int, default=25, help="tiles per fast leg")
    ap.add_argument("--tol", type=int, default=3)
    ap.add_argument("--min-hp", type=int, default=0)
    ap.add_argument("--food", default="Lobster")
    ap.add_argument("--legs", type=int, default=120, help="max legs before giving up")
    ap.add_argument("--detour-budget", type=int, default=25)
    a = ap.parse_args(argv)

    gx, gz = (int(v) for v in a.to.split(","))
    goal = (gx, gz)

    here, _ = walk.settled(a.character)
    emit(trek="start", at=list(here), goal=list(goal), stride=a.stride)

    best = abs(here[0] - gx) + abs(here[1] - gz)
    detours = 0
    legs_walked = 0

    for _ in range(a.legs):
        here, _ = walk.settled(a.character)
        gap = abs(here[0] - gx) + abs(here[1] - gz)
        if gap <= a.tol:
            emit(trek="arrived", at=list(here), legs=legs_walked, detours=detours)
            return 0

        way = step_toward(here, goal, a.stride)
        ok, hops, at = walk.leg(a.character, way, a.min_hp, a.food, calls=4, tol=a.tol)
        legs_walked += 1
        gap = abs(at[0] - gx) + abs(at[1] - gz)
        emit(leg=list(way), ok=ok, at=list(at), gap=gap, hops=len(hops))

        if gap < best:
            best = gap
            continue

        # The fast path stopped closing. Spend the expensive method here only.
        detours += 1
        emit(detour=detours, around=list(way), budget=a.detour_budget)
        res = detour(a.character, way, a.content, a.detour_budget, a.min_hp)
        after, _ = walk.settled(a.character)
        gap = abs(after[0] - gx) + abs(after[1] - gz)
        emit(detour_result=res.get("final") or res, at=list(after), gap=gap)

        if gap >= best:
            atlas.observe(
                walk.state(a.character),
                stood=list(after),
                refused=list(way),
                reason="trek stalled after detour",
            )
            emit(
                trek="stuck",
                at=list(after),
                gap=gap,
                legs=legs_walked,
                detours=detours,
                note="fast leg and detour both failed to close the gap",
            )
            return 1
        best = gap

    final, _ = walk.settled(a.character)
    emit(
        trek="out_of_legs",
        at=list(final),
        gap=abs(final[0] - gx) + abs(final[1] - gz),
        legs=legs_walked,
        detours=detours,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
