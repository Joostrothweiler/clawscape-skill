#!/usr/bin/env python3
"""Repeatedly interact with a loc that respawns, waiting for it rather than guessing.

The naive version of this is a loop that acts, sleeps a fixed interval, and acts
again. It is easy to write and it is *slow*, because the interval has to be the
worst case. Measured on the Ardougne nature rune chest, whose respawn is 30
ticks: a fixed `wait 32` between opens produced **0.4 runes a minute**, while
polling for the loc to reappear produced **4.94** -- twelve times faster, same
chest, same character, same minute of the day.

The fixed wait was not even wrong about the respawn. It was wrong about
everything else: two CLI round trips per round, plus a sleep that starts after
the action has already taken time, plus no way to notice the loc came back
early. Guessing a duration throws away the one thing the world will tell you for
free -- whether the thing is there yet.

So: poll `nearbyLocs` for the id, act the moment it appears, repeat. And count
the actual yield rather than the attempts, because an interaction that
"succeeded" is not the same as an item in the bag -- this is the same rule as
judging a training loop by whether experience moved.

    python3 recipes/harvest.py --character arete --loc 2567,2614,3314 \
        --option 2 --want "Nature rune" --rounds 200

`--option 2` on a trapped chest is "Search for traps", which disables the trap
and opens it in one action. Opening blind costs health for nothing.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk  # noqa: E402


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def count(state, name):
    if not name:
        return 0
    return sum(
        i.get("count", 1)
        for i in (state.get("inventory") or [])
        if i.get("name") == name
    )


def wait_for_loc(character, loc_id, x, z, tries=40):
    """Poll until the loc is present. Returns the state that saw it, or None."""
    for _ in range(tries):
        d = walk.state(character)
        for loc in d.get("nearbyLocs") or []:
            if loc.get("id") == loc_id and (loc.get("x"), loc.get("z")) == (x, z):
                return d
        walk.cli(character, "wait", "2")
    return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--loc", required=True, help="locId,x,z")
    ap.add_argument("--option", type=int, default=1)
    ap.add_argument("--want", default=None, help="item name to count as yield")
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--report-every", type=int, default=10)
    ap.add_argument("--min-hp", type=int, default=0)
    ap.add_argument("--food", default="Lobster")
    a = ap.parse_args(argv)

    loc_id, x, z = (int(v) for v in a.loc.split(","))
    d = walk.state(a.character)
    start = count(d, a.want)
    t0 = time.time()
    misses = 0

    emit(harvest="start", loc=a.loc, want=a.want, have=start)

    for r in range(1, a.rounds + 1):
        d = wait_for_loc(a.character, loc_id, x, z)
        if d is None:
            misses += 1
            emit(round=r, loc="did not reappear", misses=misses)
            if misses >= 5:
                emit(harvest="stopped", reason="loc stopped respawning")
                break
            continue
        misses = 0

        before = count(d, a.want)
        walk.eat(a.character, d, a.min_hp, a.food)
        walk.cli(
            a.character,
            "act",
            "interactLoc",
            "--json",
            json.dumps({"locId": loc_id, "x": x, "z": z, "optionIndex": a.option}),
        )
        walk.cli(a.character, "wait", "3")

        if r % a.report_every == 0:
            d = walk.state(a.character)
            have = count(d, a.want)
            el = max(time.time() - t0, 1)
            emit(
                round=r,
                have=have,
                gained=have - start,
                per_min=round((have - start) / el * 60, 2),
                hp=(d.get("player") or {}).get("hp"),
                free_slots=28 - len(d.get("inventory") or []),
            )
            # A harvest that stops yielding is the only reliable signal that
            # something is wrong -- the interactions keep reporting success.
            if have == before and r > a.report_every:
                emit(warn="no yield in the last round", have=have)

    d = walk.state(a.character)
    have = count(d, a.want)
    el = max(time.time() - t0, 1)
    emit(
        harvest="done",
        have=have,
        gained=have - start,
        minutes=round(el / 60, 1),
        per_min=round((have - start) / el * 60, 2),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
