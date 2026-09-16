#!/usr/bin/env python3
"""Turn items into Magic experience, and count the items rather than the casts.

Alchemy is the best experience tap a free-player character has and almost
nobody uses it, because the two numbers that decide whether it is worth doing
were both wrong in the shared notes until 2026-09-16.

    high alch   Magic 55   1 nature + 5 fire   1,625 xp   0.6 x the item's cost
    low  alch   Magic 21   1 nature + 3 fire     775 xp   0.4 x

A **staff of fire supplies the fire runes for free**, so the only consumable is
the nature rune, and the only input that can actually run out is the item.
Measured end to end: **179 high alchs took Magic 58 to 83**, +290,875 xp and
16,110 gp, standing at a bank booth, at zero risk.

The feedstock question has a surprising answer. A cooked lobster's config
`cost` is 150, so it **high-alchs for 90 gp against the 37-38 gp a general
store pays for it**. Fishing one is free. So the loop that looks like a Fishing
grind is really a Magic engine: fish it, cook it, alch it.

    python3 recipes/alch.py --character arete --item Lobster --keep 4

Two things this does that a hand-rolled loop does not:

  - **It counts the item, not the dispatch.** An earlier session recorded that
    "about one cast in five is a silent no-op that still returns success". Over
    179 casts that did not reproduce even once, so the note is doubtful -- but
    the discipline it implies is free and the failure it guards against is
    invisible, so the item count is the source of truth here either way.
  - **It keeps a food reserve.** `--keep` exists because the feedstock is often
    also the food, and a character that alchs its own larder to zero is one
    fight away from a corpse run. It refuses to go below it.

Wield the staff first: `useInventoryItem` with the staff's slot and its Wield
option index. `useItem` is not an action type in this world, which is a fast
way to waste a few minutes.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk  # noqa: E402

SPELL = {"high": 1178, "low": 1162}
XP = {"high": 1625, "low": 775}


def emit(**kw):
    print(json.dumps(kw), flush=True)


def st(ch):
    return walk.state(ch) or {}


def count(d, name):
    return sum(1 for i in (d.get("inventory") or []) if i["name"] == name)


def stack(d, name):
    return sum(
        i.get("amount") or i.get("count") or 1
        for i in (d.get("inventory") or [])
        if i["name"] == name
    )


def xp(d, skill="Magic"):
    for s in d.get("skills") or []:
        if s["name"] == skill:
            return s["experience"]
    return 0


def level(d, skill="Magic"):
    for s in d.get("skills") or []:
        if s["name"] == skill:
            return s["level"]
    return 0


def wield_staff(ch, d):
    """Fire runes are free while the staff is in hand, and only then."""
    for i in d.get("inventory") or []:
        if i["name"].startswith("Staff of fire"):
            opts = [o.get("text") for o in (i.get("optionsWithIndex") or [])]
            idx = (opts.index("Wield") + 1) if "Wield" in opts else 2
            walk.cli(
                ch,
                "act",
                "useInventoryItem",
                "--json",
                json.dumps({"slot": i["slot"], "optionIndex": idx}),
            )
            walk.cli(ch, "wait", "3")
            return True
    return any(
        (e.get("name") or "").startswith("Staff of fire")
        for e in (d.get("equipment") or [])
    )


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--item", default="Lobster")
    ap.add_argument("--spell", choices=("high", "low"), default="high")
    ap.add_argument("--keep", type=int, default=4, help="never alch below this many")
    ap.add_argument("--max-casts", type=int, default=200)
    ap.add_argument("--report-every", type=int, default=10)
    a = ap.parse_args(argv)
    ch, comp = a.character, SPELL[a.spell]

    d = st(ch)
    if not d:
        raise SystemExit(json.dumps({"error": "no state"}))
    need = 55 if a.spell == "high" else 21
    if level(d) < need:
        raise SystemExit(json.dumps({"error": "Magic %d, need %d" % (level(d), need)}))
    if not wield_staff(ch, d):
        emit(warning="no staff of fire; every cast will need 5 fire runes of its own")
    d = st(ch)
    x0, l0, t0 = xp(d), level(d), time.time()
    emit(
        start={
            "magic": l0,
            "xp": x0,
            a.item: count(d, a.item),
            "nature_runes": stack(d, "Nature rune"),
        }
    )

    casts = noops = 0
    while casts < a.max_casts:
        d = st(ch)
        have = count(d, a.item)
        if have <= a.keep:
            reason = "reserve of %d reached" % a.keep
            break
        if stack(d, "Nature rune") < 1:
            reason = "out of nature runes"
            break
        slot = next(i["slot"] for i in d["inventory"] if i["name"] == a.item)
        walk.cli(
            ch,
            "act",
            "spellOnItem",
            "--json",
            json.dumps({"slot": slot, "spellComponent": comp}),
        )
        walk.cli(ch, "wait", "4")
        casts += 1
        if count(st(ch), a.item) == have:
            noops += 1
        if casts % a.report_every == 0:
            d = st(ch)
            emit(
                casts=casts,
                noops=noops,
                magic=level(d),
                xp_gained=xp(d) - x0,
                left=count(d, a.item),
                natures=stack(d, "Nature rune"),
            )
    else:
        reason = "max casts"

    d = st(ch)
    emit(
        done=True,
        casts=casts,
        silent_noops=noops,
        reason=reason,
        magic=[l0, level(d)],
        xp_gained=xp(d) - x0,
        expected_xp=casts * XP[a.spell],
        coins=stack(d, "Coins"),
        minutes=round((time.time() - t0) / 60, 1),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
