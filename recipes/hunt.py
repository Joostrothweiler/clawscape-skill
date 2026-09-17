#!/usr/bin/env python3
"""Kill a named NPC, eat when hurt, and actually pick the loot up.

`train.py` repeats an interaction until a skill moves, which is right for
pickpocketing and wrong for killing things, because it does two things a hunt
cannot live with: it **stops at `--min-hp` without eating**, and it **never
picks anything up**. A character using it to farm drops fights until it is
nearly dead and then stands in a pile of its own loot doing nothing.

That matters because loot is usually the point. Moss giants are worth killing
not for the combat xp but for roughly 53 gp of alchable items per kill plus the
nature runes that fuel the alching -- see `references/alchemy.md`. A kill whose
drop is left on the ground is a wasted kill, and ground items despawn.

So this loop is: find the target, attack it, eat when health drops, sweep the
ground for anything worth taking, repeat. It stops when food runs out rather
than when health does, because a character that keeps fighting without food is
a character about to make a donation to the respawn point.

    python3 recipes/hunt.py --character arete --npc "Moss giant" \
        --take "Nature rune" --take "Black sq shield" --take Coins --rounds 200

`--take` is repeatable and matches by name. Give it the things worth carrying;
everything else is left where it falls, because inventory space is the real
budget and 28 slots fill faster than they look.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atlas  # noqa: E402
import walk  # noqa: E402

# Anything worth taking by default: alchable metal, runes, and money.
DEFAULT_TAKE = (
    "bones",
    "rune",
    "coins",
    "shield",
    "sword",
    "helm",
    "spear",
    "platebody",
    "platelegs",
    "bar",
    "arrow",
    "staff",
)


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def state(character):
    """State, reconnecting rather than dying -- a hunt runs for a long time."""
    for attempt in range(3):
        try:
            d = walk.state(character)
            if d:
                return d
        except SystemExit:
            pass
        emit(reconnecting=attempt + 1)
        walk.cli(character, "connect", "--character", character)
        walk.cli(character, "wait", "3")
    return None


def counts(d):
    out = {}
    for i in d.get("inventory") or []:
        out[i["name"]] = out.get(i["name"], 0) + i.get("count", 1)
    return out


def option_index(npc, want):
    """The opIndex for a named option, read from the NPC rather than guessed.

    Option indices are per-NPC, the same trap as combat style indices: a
    hardcoded number is right for one creature and wrong for the next.
    """
    for o in npc.get("optionsWithIndex") or []:
        if (o.get("text") or "").lower() == (want or "").lower():
            return o.get("opIndex", 1)
    return 1


def wanted(name, takes):
    low = (name or "").lower()
    return any(t.lower() in low for t in takes)


def bury_bones(character, d):
    """Bury any bones carried. Trains Prayer from loot that is otherwise junk.

    Bones are the one drop worth taking that is not worth alching or selling:
    they occupy a slot, they are dropped by everything, and burying them is
    free Prayer xp. A hunt that leaves them on the ground throws away a skill.
    """
    buried = 0
    for item in list(d.get("inventory") or []):
        name = (item.get("name") or "").lower()
        if "bones" not in name:
            continue
        opts = {
            (o.get("text") or "").lower(): o.get("opIndex", 1)
            for o in item.get("optionsWithIndex") or []
        }
        idx = opts.get("bury")
        if idx is None:
            continue
        walk.cli(
            character,
            "act",
            "useInventoryItem",
            "--json",
            json.dumps({"slot": item.get("slot"), "optionIndex": idx}),
        )
        walk.cli(character, "wait", "2")
        buried += 1
    return buried


def eat(character, d, min_hp, food):
    p = d.get("player") or {}
    if p.get("hp", 99) >= min_hp:
        return False
    have = [i for i in d.get("inventory") or [] if i["name"] == food]
    if not have:
        return False
    walk.cli(
        character,
        "act",
        "useInventoryItem",
        "--json",
        json.dumps({"slot": have[0]["slot"], "optionIndex": 1}),
    )
    walk.cli(character, "wait", "3")
    return True


def sweep(character, takes, limit=6):
    """Pick up nearby drops we care about. Returns how many were taken."""
    walk.cli(character, "act", "scanGroundItems")
    walk.cli(character, "wait", "1")
    d = state(character)
    if not d:
        return 0
    took = 0
    for item in (d.get("groundItems") or [])[:limit]:
        name = item.get("name")
        if not wanted(name, takes):
            continue
        # Walk to it first. Drops land at the TARGET's feet, not yours, and
        # `pickupItem` on something out of reach just answers "I can't reach
        # that!". Arrows especially: every shot is an arrow on the ground by
        # the corpse, and a ranged hunt that does not collect them runs out.
        walk.cli(
            character,
            "act",
            "walkTo",
            "--json",
            json.dumps({"x": item.get("x"), "z": item.get("z"), "running": True}),
        )
        walk.cli(character, "wait", "3")
        walk.cli(
            character,
            "act",
            "pickupItem",
            "--json",
            json.dumps(
                {
                    "x": item.get("x"),
                    "z": item.get("z"),
                    "itemId": item.get("id"),
                }
            ),
        )
        walk.cli(character, "wait", "2")
        took += 1
    return took


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--npc", required=True, help="name, matched case-insensitively")
    ap.add_argument("--option", default="Attack")
    ap.add_argument("--take", action="append", default=[])
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--min-hp", type=int, default=45)
    ap.add_argument("--food", default="Lobster")
    ap.add_argument("--report-every", type=int, default=10)
    ap.add_argument(
        "--safespot",
        default=None,
        help="x,z to return to after every attack; the tile the target cannot reach",
    )
    ap.add_argument(
        "--target",
        default=None,
        help="x,z of the ONE SPAWN TILE to attack; required for safespotting",
    )
    ap.add_argument(
        "--target-radius",
        type=int,
        default=5,
        help=(
            "how far from --target the pinned spawn may have wandered. An npc's "
            "`wanderrange` means it is almost never standing on its own spawn "
            "tile, so an exact match pins nothing; default is a moss giant's "
            "maxrange of 5"
        ),
    )
    ap.add_argument(
        "--weapon-range",
        type=int,
        default=0,
        help=(
            "skip attacks on targets further than this, in tiles. Attacking "
            "something out of range makes the character WALK to it, which is "
            "exactly how a safespot is lost; the obj param is 10 for a longbow "
            "and 7 for a shortbow. 0 disables the check"
        ),
    )
    ap.add_argument(
        "--kite",
        type=int,
        default=0,
        help="tiles to back away from the target after each attack",
    )
    a = ap.parse_args(argv)

    takes = a.take or list(DEFAULT_TAKE)
    pin = None
    if a.target:
        pin = tuple(int(v) for v in a.target.split(","))
    safespot = None
    if a.safespot:
        safespot = tuple(int(v) for v in a.safespot.split(","))
    d = state(a.character)
    if not d:
        raise SystemExit(json.dumps({"error": "no state"}))
    start = counts(d)
    t0 = time.time()
    kills = 0
    taken = 0
    buried = 0

    p = d.get("player") or {}
    hp, maxhp = p.get("hp", 0), p.get("maxHp", 0) or 1
    here0 = (p.get("worldX"), p.get("worldZ"))

    # Never open a fight already hurt. A character that starts below its own
    # heal threshold is a character that dies before the first eat. Measured
    # the hard way: sent in at 52/94 against level 42 giants with Defence 1,
    # dead before the hunt loop even started -- its first log line read hp 0.
    if hp < max(a.min_hp, int(0.8 * maxhp)):
        emit(topping_up=True, hp=hp, of=maxhp)
        for _ in range(12):
            d = state(a.character) or d
            if (d.get("player") or {}).get("hp", 0) >= int(0.9 * maxhp):
                break
            if not eat(a.character, d, maxhp, a.food):
                break
        d = state(a.character) or d
        hp = (d.get("player") or {}).get("hp", 0)
        if hp < max(a.min_hp, int(0.7 * maxhp)):
            emit(hunt="refused", reason="too hurt to start", hp=hp, of=maxhp)
            return 1

    emit(hunt="start", npc=a.npc, take=takes, hp=hp, of=maxhp)

    for r in range(1, a.rounds + 1):
        d = state(a.character)
        if not d:
            emit(hunt="stopped", reason="lost the session")
            break

        # Death is a teleport, not an error message. The only reliable sign is
        # that the character is suddenly somewhere else with full health, so a
        # loop that does not check position keeps swinging at an empty field
        # hundreds of tiles from where it died -- 44 rounds of "no target in
        # range" before anybody noticed.
        pp = d.get("player") or {}
        moved = abs(pp.get("worldX", 0) - here0[0]) + abs(
            pp.get("worldZ", 0) - here0[1]
        )
        if moved > 60:
            emit(
                hunt="stopped",
                reason="died and respawned",
                at=[pp.get("worldX"), pp.get("worldZ")],
                round=r,
            )
            break

        # Food is the budget. Out of food is out of hunt, not a reason to
        # keep swinging and find out what happens.
        if not [i for i in d.get("inventory") or [] if i["name"] == a.food]:
            emit(hunt="stopped", reason="out of food", round=r)
            break
        if eat(a.character, d, a.min_hp, a.food):
            d = state(a.character) or d

        target = None
        for n in d.get("nearbyNpcs") or []:
            if (a.npc or "").lower() not in (n.get("name") or "").lower():
                continue
            if (n.get("hp") is not None) and n.get("hp", 1) <= 0:
                continue
            # A safespot works against ONE spawn, not against the species. The
            # first safespot test failed for exactly this reason: the loop
            # attacked the nearest giant, seven tiles off at the edge of bow
            # range, so the character walked in to close -- and the tile chosen
            # to be unreachable by a different giant became irrelevant.
            if pin is not None:
                # Match the SPAWN, not the tile it happens to be standing on.
                # A moss giant wanders 3 tiles, so an exact comparison pins
                # nothing and the loop silently falls through to "no target".
                if (
                    max(abs(n.get("x", 0) - pin[0]), abs(n.get("z", 0) - pin[1]))
                    > a.target_radius
                ):
                    continue
            if a.weapon_range:
                # Measure from the SAFESPOT, not from where the character is
                # standing right now. Measuring from the live position makes
                # this a ratchet: one drift puts her closer to the camp, which
                # brings more giants inside range of the new spot, which pulls
                # her further in. Measured at Ardougne, it walked her 14 tiles
                # off her tile with a giant at distance 1. The safespot is the
                # tile she is going to shoot from, so it is the one that
                # decides what is in range.
                origin = safespot or (
                    (d.get("player") or {}).get("worldX"),
                    (d.get("player") or {}).get("worldZ"),
                )
                if (
                    max(abs(n.get("x", 0) - origin[0]), abs(n.get("z", 0) - origin[1]))
                    > a.weapon_range
                ):
                    continue
            target = n
            break
        if target is None:
            taken += sweep(a.character, takes)
            # sweep() walks to the drop, so this branch leaks the tile too.
            if safespot:
                for _ in range(4):
                    at_now, _ = walk.settled(a.character)
                    if tuple(at_now) == safespot:
                        break
                    walk.cli(
                        a.character,
                        "act",
                        "walkTo",
                        "--json",
                        json.dumps(
                            {"x": safespot[0], "z": safespot[1], "running": True}
                        ),
                    )
                    walk.cli(a.character, "wait", "6")
            emit(round=r, note="no target in range", taken=taken)
            walk.cli(a.character, "wait", "5")
            continue

        walk.cli(
            a.character,
            "act",
            "interactNpc",
            "--json",
            json.dumps(
                {
                    "npcIndex": target.get("index"),
                    "optionIndex": option_index(target, a.option),
                }
            ),
        )
        walk.cli(a.character, "wait", "8")

        # Attacking does NOT normally move you: `player_combat.rs2` fires from
        # where you stand whenever the target is inside the weapon's
        # `attackrange`. Measured on 2026-09-16, every attack issued with a
        # clear line of sight at 3 to 10 tiles moved the character zero tiles.
        #
        # But it is not every attack. Roughly one in six still walked her in
        # with a clear line -- most likely the target moving between the state
        # read and the dispatch, so the engine saw a blocked line. That is
        # cheap to correct and expensive to ignore, so re-assert the tile after
        # every attack. Against a leashed monster, stepping back outside its
        # `maxrange` breaks contact for good rather than merely postponing it.
        kills += 1
        taken += sweep(a.character, takes)
        buried += bury_bones(a.character, state(a.character) or {})
        # The re-assert has to be the LAST thing in the round. It used to run
        # before the loot sweep, and `sweep` and `bury_bones` both walk the
        # character to the drop, so every round ended standing on the corpse
        # pile inside the giant's reach instead of on the safespot. Measured at
        # the Ardougne camp: the character drifted 9 tiles off her tile and
        # took 15 damage over a run that should have taken none.
        #
        # One walkTo is also not enough. A call moves 7 to 8 tiles, so a 9-tile
        # return needs more than one, and `wait 4` does not even finish the
        # first. Loop until the tile is actually under her.
        if safespot:
            for _ in range(6):
                at_now, _ = walk.settled(a.character)
                if tuple(at_now) == safespot:
                    break
                walk.cli(
                    a.character,
                    "act",
                    "walkTo",
                    "--json",
                    json.dumps({"x": safespot[0], "z": safespot[1], "running": True}),
                )
                walk.cli(a.character, "wait", "6")
        atlas.observe(state(a.character))

        if r % a.report_every == 0:
            d = state(a.character) or d
            now = counts(d)
            gained = {
                k: now.get(k, 0) - start.get(k, 0)
                for k in set(now) | set(start)
                if now.get(k, 0) - start.get(k, 0) > 0
            }
            emit(
                round=r,
                engaged=kills,
                picked_up=taken,
                bones_buried=buried,
                hp=(d.get("player") or {}).get("hp"),
                food=now.get(a.food, 0),
                free_slots=28 - len(d.get("inventory") or []),
                gained=gained,
                minutes=round((time.time() - t0) / 60, 1),
            )

    d = state(a.character) or {}
    now = counts(d)
    emit(
        hunt="done",
        engaged=kills,
        picked_up=taken,
        bones_buried=buried,
        minutes=round((time.time() - t0) / 60, 1),
        gained={
            k: now.get(k, 0) - start.get(k, 0)
            for k in set(now) | set(start)
            if now.get(k, 0) - start.get(k, 0) > 0
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
