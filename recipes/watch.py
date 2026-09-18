#!/usr/bin/env python3
"""Watch a character the way a person watching the screen would.

Every failure in the 2026-09-17 session was visible in live state and missed,
because the loop was judged by its own reports instead of by the character.
A person glancing at the screen caught all of them in seconds:

    "you're attacking with a staff"      -> equipment slot 3
    "you're left with 2 arrows"          -> a falling trend, not a level
    "I see loot on the floor"            -> groundItems persisting across polls
    "and arete being hit"                -> HP falling while on the safespot
    "walking within fights"              -> position moving between attacks

So this asserts the invariants an activity implies and shouts when one breaks.
It does not drive the character and never fixes anything: the point is to make
a silent failure loud, early, from outside the loop that is failing.

Two ideas it is built on, both paid for:

  - **Judge by the artifact, not the instrumentation.** A loop reporting
    `attacks: 55` while xp sits still is a loop lying to you in good faith.
  - **A resource is a derivative.** 200 arrows is not information. 200 then
    150 then 104 is.

    python3 recipes/watch.py --character arete --safespot 2546,3400 \
        --weapon-contains bow --min-ammo 40 --xp-skill Ranged
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk  # noqa: E402


def emit(**kw):
    print(json.dumps(kw), flush=True)


def count(d, needle):
    total = 0
    for i in (d.get("inventory") or []) + (d.get("equipment") or []):
        if needle.lower() in (i.get("name") or "").lower():
            total += i.get("amount") or i.get("count") or 1
    return total


def xp(d, skill):
    return next(
        (s["experience"] for s in d.get("skills") or [] if s["name"] == skill), 0
    )


def check(d, a, history):
    """Return the list of broken invariants. Empty is the healthy answer."""
    broken = []
    p = d.get("player") or {}

    if a.weapon_contains:
        worn = next(
            (e.get("name") for e in (d.get("equipment") or []) if e.get("slot") == 3),
            None,
        )
        if not worn or a.weapon_contains.lower() not in worn.lower():
            broken.append(
                {"invariant": "weapon", "want": a.weapon_contains, "worn": worn}
            )

    if a.min_ammo:
        ammo = count(d, "arrow") + count(d, "bolt")
        if ammo < a.min_ammo:
            broken.append({"invariant": "ammo", "have": ammo, "floor": a.min_ammo})

    if a.food:
        if count(d, a.food) < 1 and not any(
            (o.get("text") or "") == "Eat"
            for i in (d.get("inventory") or [])
            for o in (i.get("optionsWithIndex") or [])
        ):
            broken.append({"invariant": "food", "have": 0})

    if a.safespot:
        here = (p.get("worldX"), p.get("worldZ"))
        off = max(abs(here[0] - a.safespot[0]), abs(here[1] - a.safespot[1]))
        if off > a.drift:
            broken.append({"invariant": "position", "off_tile": off, "at": list(here)})

    # Trends. A level is not information; a direction is.
    if len(history) >= 3:
        hps = [h["hp"] for h in history[-3:]]
        if hps[0] > hps[1] > hps[2]:
            broken.append({"invariant": "hp_trend", "samples": hps})
        if a.xp_skill:
            xps = [h["xp"] for h in history[-3:]]
            if xps[0] == xps[1] == xps[2]:
                broken.append(
                    {"invariant": "xp_stalled", "skill": a.xp_skill, "xp": xps[0]}
                )
        grounds = [h["ground"] for h in history[-3:]]
        if all(g and g == grounds[0] for g in grounds):
            broken.append({"invariant": "loot_uncollected", "items": grounds[0]})

    return broken


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--safespot", help="x,z the character should be standing on")
    ap.add_argument("--drift", type=int, default=3, help="tiles of slack on --safespot")
    ap.add_argument("--weapon-contains", help="substring the slot-3 item must match")
    ap.add_argument("--min-ammo", type=int, default=0)
    ap.add_argument("--food", default="")
    ap.add_argument("--xp-skill", help="skill whose xp must keep moving")
    ap.add_argument("--interval", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=0, help="0 runs until stopped")
    a = ap.parse_args(argv)
    if a.safespot:
        a.safespot = tuple(int(v) for v in a.safespot.split(","))

    history = []
    last = None
    i = 0
    while not a.rounds or i < a.rounds:
        i += 1
        d = walk.state(a.character)
        if not d or "player" not in d:
            emit(alarm=[{"invariant": "connected", "detail": "no state"}])
            time.sleep(a.interval)
            continue
        p = d["player"]
        history.append(
            {
                "hp": p["hp"],
                "xp": xp(d, a.xp_skill) if a.xp_skill else 0,
                "ground": sorted(
                    (g.get("name") or "") for g in (d.get("groundItems") or [])
                ),
            }
        )
        history[:] = history[-6:]
        broken = check(d, a, history)
        fingerprint = json.dumps([b["invariant"] for b in broken])
        if broken and fingerprint != last:
            emit(alarm=broken, at=[p["worldX"], p["worldZ"]], hp=p["hp"])
        elif not broken and last not in (None, "[]"):
            emit(ok=True, at=[p["worldX"], p["worldZ"]], hp=p["hp"])
        last = fingerprint
        time.sleep(a.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
