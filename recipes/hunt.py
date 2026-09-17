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


def sweep(character, takes, limit=6, within=None, origin=None):
    """Pick up nearby drops we care about. Returns how many were taken.

    `within` and `origin` bound how far the sweep will wander. A safespotting
    camp must not chase a drop into the leash zone every round, but it also
    must not leave everything lying there: moving the sweep to the idle branch
    alone meant that on a tile covering three spawns, where there are almost no
    idle rounds, **ten kills in a row were collected from not at all** while
    big bones and coins sat on the character's own tile. So the round-by-round
    sweep is bounded to what is safe to reach from the safespot, and the
    unbounded one still runs while waiting for a respawn.
    """
    walk.cli(character, "act", "scanGroundItems")
    walk.cli(character, "wait", "1")
    d = state(character)
    if not d:
        return 0
    # Rank before truncating. `scanGroundItems` returns whatever order it
    # likes and `limit` throws away the tail, so a scatter of arrows could
    # crowd out the drop that was worth the walk. Arrows first because they are
    # the ammunition and the hunt stops without them, then bones because they
    # are the Prayer, then the rest by value. Ties break on distance so the
    # cheap nearby pickups still happen on the way.
    AMMO = ("arrow", "bolt", "dart")
    BONES = ("bones",)
    VALUABLE = (
        "rune",
        "coins",
        "shield",
        "spear",
        "sword",
        "helm",
        "platebody",
        "platelegs",
        "bar",
        "staff",
        "gem",
        "emerald",
        "sapphire",
        "ruby",
        "diamond",
    )

    def rank(it):
        n = (it.get("name") or "").lower()
        if any(k in n for k in AMMO):
            tier = 0
        elif any(k in n for k in BONES):
            tier = 1
        elif any(k in n for k in VALUABLE):
            tier = 2
        else:
            tier = 3
        return (tier, it.get("distance", 99))

    took = 0
    seen = [(i.get("name"), i.get("distance")) for i in (d.get("groundItems") or [])]
    skipped = []
    for item in sorted(d.get("groundItems") or [], key=rank)[:limit]:
        name = item.get("name")
        if not wanted(name, takes):
            skipped.append((name, "not wanted"))
            continue
        if within is not None and origin is not None and rank(item)[0] >= 3:
            if (
                max(
                    abs(item.get("x", 0) - origin[0]),
                    abs(item.get("z", 0) - origin[1]),
                )
                > within
            ):
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
    # Only worth saying when it went wrong: something on the ground that was
    # wanted and still not taken. A quiet sweep needs no commentary.
    if skipped or (seen and not took):
        emit(sweep_saw=len(seen), sweep_took=took, sweep_skipped=skipped[:6])
    return took


def last_game_message(d):
    msgs = d.get("gameMessages") or []
    return msgs[-1].get("text") if msgs else "no message"


def rewield_ammo(character, d):
    """Put recovered arrows back in the quiver.

    A ranged camp recovers most of its own ammunition, but `sweep` puts the
    arrows in the INVENTORY and the quiver stays empty. The loop then keeps
    reporting engagements while firing nothing at all: the only trace anywhere
    is "There is no ammo left in your quiver." in the message log. Four minutes
    of a three-spawn camp were spent this way with four giants standing in
    range.
    """
    equipped = any(
        (e.get("name") or "").lower().endswith(("arrow", "arrows", "bolt", "bolts"))
        for e in (d.get("equipment") or [])
    )
    if equipped:
        return True
    for i in d.get("inventory") or []:
        name = (i.get("name") or "").lower()
        if not (name.endswith("arrow") or name.endswith("bolts")):
            continue
        idx = next(
            (
                o.get("opIndex")
                for o in (i.get("optionsWithIndex") or [])
                if o.get("text") == "Wield"
            ),
            2,
        )
        walk.cli(
            character,
            "act",
            "useInventoryItem",
            "--json",
            json.dumps({"slot": i["slot"], "optionIndex": idx}),
        )
        walk.cli(character, "wait", "3")
        # Verify rather than trust the dispatch: a wrong optionIndex answers
        # success and leaves the arrows exactly where they were.
        return any(
            (e.get("name") or "").lower().endswith(("arrow", "arrows", "bolt", "bolts"))
            for e in ((walk.state(character) or {}).get("equipment") or [])
        )
    return False


ALCH_SKIP = (
    "bones",
    "arrow",
    "bolt",
    "dart",
    "coins",
    "nature rune",
    "salmon",
    "lobster",
    "trout",
)


def alch_valuables(character, keep_runes=10, spell=1178):
    """Turn the drops into Magic xp and coins instead of carrying them home.

    High alch pays 1,625 Magic xp and 0.6x the item's value, and the xp does
    not depend on the item, so a camp that drops alchables is a Magic engine
    that happens to also be a Ranged one. The nature rune is the only real
    consumable; a staff of fire supplies the fire runes.

    The staff has to be WIELDED, which means putting the bow down, so this is
    batched rather than done per drop. Everything is swapped back afterwards.
    """
    d = walk.state(character) or {}
    runes = sum(
        i.get("amount") or i.get("count") or 0
        for i in (d.get("inventory") or [])
        if i["name"] == "Nature rune"
    )
    targets = [
        i
        for i in (d.get("inventory") or [])
        if not any(k in (i["name"] or "").lower() for k in ALCH_SKIP)
        and i["name"] not in ("Staff of fire", "Oak longbow", "Lobster pot")
    ]
    if runes <= keep_runes or not targets:
        return 0

    def wield(name):
        for i in (walk.state(character) or {}).get("inventory") or []:
            if i["name"] == name:
                idx = next(
                    (
                        o.get("opIndex")
                        for o in (i.get("optionsWithIndex") or [])
                        if o.get("text") in ("Wield", "Wear")
                    ),
                    2,
                )
                walk.cli(
                    character,
                    "act",
                    "useInventoryItem",
                    "--json",
                    json.dumps({"slot": i["slot"], "optionIndex": idx}),
                )
                walk.cli(character, "wait", "3")
                return True
        return False

    if not wield("Staff of fire"):
        return 0
    cast = 0
    for item in targets:
        d = walk.state(character) or {}
        row = next(
            (i for i in d.get("inventory") or [] if i["name"] == item["name"]), None
        )
        if row is None:
            continue
        before = len(d.get("inventory") or [])
        walk.cli(
            character,
            "act",
            "spellOnItem",
            "--json",
            json.dumps({"slot": row["slot"], "spellComponent": spell}),
        )
        walk.cli(character, "wait", "4")
        if len((walk.state(character) or {}).get("inventory") or []) < before:
            cast += 1
    # Put the weapon back, and CHECK. If this silently fails the character is
    # left holding a staff with no bow, every subsequent attack does nothing,
    # and the loop reports a clean run while the xp sits still. That happened:
    # the staff stayed equipped and the hunt quietly stopped landing hits.
    for name in ("Oak longbow", "Longbow", "Shortbow"):
        if wield(name):
            break
    weapon = next(
        (
            e.get("name")
            for e in ((walk.state(character) or {}).get("equipment") or [])
            if e.get("slot") == 3
        ),
        None,
    )
    if weapon is None or "staff" in (weapon or "").lower():
        emit(
            alch_warning="weapon not restored after alching",
            weapon=weapon,
            casts=cast,
        )
    return cast


def hold_safespot(character, safespot, tries=6):
    """Put the character back on its tile, and confirm it rather than assume.

    A single `walkTo` moves 7 to 8 tiles, so any return longer than that needs
    more than one call, and the settled read is what proves it happened.
    """
    if not safespot:
        return True
    for _ in range(tries):
        at_now, _ = walk.settled(character)
        if tuple(at_now) == safespot:
            return True
        walk.cli(
            character,
            "act",
            "walkTo",
            "--json",
            json.dumps({"x": safespot[0], "z": safespot[1], "running": True}),
        )
        walk.cli(character, "wait", "6")
    return tuple(walk.settled(character)[0]) == safespot


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
        action="append",
        default=None,
        help="x,z of a SPAWN TILE to attack; required for safespotting. "
        "Repeatable: one stand tile often sits inside weapon range of several "
        "spawns while still outside every leash, and pinning only one leaves "
        "the loop idle through the other respawns. At the Ardougne moss giant "
        "camp, 24 of 38 rounds read 'no target in range' against one spawn, "
        "and (2546,3400) covers three at 8, 8 and 9 tiles.",
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
        "--sweep-every",
        type=int,
        default=0,
        help="every N rounds, walk the kill site and collect properly rather "
        "than only what landed within --safe-pickup. Needed because the target "
        "wanders before it dies, so the drop is usually outside that radius, "
        "and on a multi-spawn tile the loop never goes idle long enough for "
        "the unbounded sweep to run. Without it, 42 kills produced 5 bones. "
        "DEFAULT 0, because measured end to end it costs more than it wins: "
        "`sweep` walks to each drop individually, so a kill-site pass every "
        "other round slowed the loop until almost nothing happened. Over ten "
        "minutes at --sweep-every 2 the character gained 2,200 Ranged xp and "
        "buried ZERO bones; the same camp at 0 gained 6,700 xp and buried two "
        "bones in under two minutes. The per-round bounded sweep already "
        "collects the corpse most of the time, because attacking pulls the "
        "character toward the target often enough to bring the drop inside "
        "--safe-pickup. Turn this on only for a camp where the drop really "
        "does land out of reach, and measure it.",
    )
    ap.add_argument(
        "--loot-sortie",
        type=int,
        default=1,
        help="on a loot round, step out to the pinned spawns to scan from "
        "there before returning. scanGroundItems reaches only about 13 tiles "
        "and is centred on the character, so a corpse 14 or 16 tiles from the "
        "safespot is invisible from it and its drops are never collected. "
        "0 disables the sortie.",
    )
    ap.add_argument(
        "--loot-every",
        type=int,
        default=6,
        help="sweep for loot every N rounds. A round is one ATTACK, not one "
        "kill, and a moss giant takes about a dozen, so 1 means breaking off "
        "after every shot to fetch the arrow just fired.",
    )
    ap.add_argument(
        "--alch-every",
        type=int,
        default=40,
        help="every N rounds, high-alch the valuables carried. Turns the "
        "camp's drops into Magic xp and coins rather than a bank trip. "
        "0 disables it.",
    )
    ap.add_argument(
        "--alch-keep",
        type=int,
        default=10,
        help="never alch below this many nature runes",
    )
    ap.add_argument(
        "--safe-pickup",
        type=int,
        default=3,
        help="how far from the safespot the per-round sweep will step for a "
        "drop. Kept small on purpose: the loot lands at the corpse, which is "
        "inside the leash, and the point of the tile is not to go there. The "
        "unbounded sweep still runs while waiting for a respawn.",
    )
    ap.add_argument(
        "--kite",
        type=int,
        default=0,
        help="tiles to back away from the target after each attack",
    )
    a = ap.parse_args(argv)

    takes = a.take or list(DEFAULT_TAKE)
    pins = None
    if a.target:
        pins = [tuple(int(v) for v in t.split(",")) for t in a.target]
    safespot = None
    if a.safespot:
        safespot = tuple(int(v) for v in a.safespot.split(","))
    d = state(a.character)
    if not d:
        raise SystemExit(json.dumps({"error": "no state"}))
    # Whether ammunition matters at all. A scimitar has no arrows and never
    # will, so the out-of-ammo stop below must not fire for a melee camp.
    #
    # Read the WEAPON, not the quiver. The first version of this checked
    # whether ammunition was equipped at start, and a run that began with an
    # empty quiver and 56 arrows in the pack therefore decided it was a melee
    # camp: rewield_ammo never ran, the out-of-ammo stop was gated off the same
    # flag, and the loop fired nothing for five minutes while reporting nothing
    # wrong. The guard against the silent stop produced the silent stop.
    weapon = next(
        (
            (e.get("name") or "").lower()
            for e in (d.get("equipment") or [])
            if e.get("slot") == 3
        ),
        "",
    )
    ranged_camp = any(w in weapon for w in ("bow", "crossbow", "sling", "dart"))
    start = counts(d)
    t0 = time.time()
    killed = 0
    alched = 0
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
        # Match the named food first, then anything else edible. Stopping with
        # a pack full of lobster because --food said Salmon is a silly way to
        # end a run, and it happened.
        edible = [i for i in d.get("inventory") or [] if i["name"] == a.food] or [
            i
            for i in d.get("inventory") or []
            if any(
                (o.get("text") or "") == "Eat" for o in i.get("optionsWithIndex") or []
            )
        ]
        if not edible:
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
            if pins:
                # Match the SPAWN, not the tile it happens to be standing on.
                # A moss giant wanders 3 tiles, so an exact comparison pins
                # nothing and the loop silently falls through to "no target".
                if not any(
                    max(abs(n.get("x", 0) - p[0]), abs(n.get("z", 0) - p[1]))
                    <= a.target_radius
                    for p in pins
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
        if ranged_camp and not rewield_ammo(a.character, d):
            # No ammunition equipped and none in the pack. Every further attack
            # will answer success and fire nothing, which is the same silent
            # stop the quiver bug produced, one level up: there the arrows were
            # in the inventory, here there are none at all. Stop and say so
            # rather than grinding rounds into an empty bow.
            emit(
                done=True,
                reason="out of ammunition",
                rounds=r,
                engaged=kills,
                message=last_game_message(state(a.character) or {}),
            )
            break
        d = state(a.character) or d

        if target is None:
            # Nothing alive in range, so this is the safe window: collect the
            # drops now, then get back on the tile before the respawn.
            taken += sweep(a.character, takes)
            buried += bury_bones(a.character, state(a.character) or {})
            hold_safespot(a.character, safespot, tries=4)
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

        # ORDER MATTERS, and getting it wrong has cost something every time.
        #
        # 1. Get back on the tile. ALWAYS, every round, before anything else.
        #    This used to sit behind a `continue` that skipped it on non-loot
        #    rounds, so across a twelve-attack fight the character drifted into
        #    melee and was still being hit while the loop reported nothing
        #    wrong.
        # 2. Loot on a CADENCE, not every round and not on a detected kill. A
        #    round is one attack and a giant takes about a dozen, so looting
        #    every round means breaking off after each shot to fetch the arrow
        #    just fired. Detecting the kill instead sounds right and is
        #    fragile: the loop re-acquires a target every round, so "is the
        #    thing I attacked still alive" answered yes forever in one version
        #    and almost never in the next. A counter cannot be wrong about
        #    itself.
        if safespot:
            at_now, _ = walk.settled(a.character)
            if tuple(at_now) != safespot:
                hold_safespot(a.character, safespot, tries=4)

        if r % a.loot_every:
            continue
        killed += 1

        # Arrows first (they are the ammunition and they are free to carry),
        # then bones (Prayer), then the rest by value. `sweep` ranks them.
        origin = safespot
        if origin is None:
            pl = (state(a.character) or {}).get("player") or {}
            if pl.get("worldX") is not None:
                origin = (pl["worldX"], pl["worldZ"])
        taken += sweep(
            a.character, takes, limit=10, within=a.safe_pickup, origin=origin
        )
        # `scanGroundItems` is centred on the character and reaches about 13
        # tiles. The corpse is often further: the spawn sits 8 or 9 tiles from
        # a safespot and the target wanders up to `wanderrange` before dying,
        # so a drop at 14 or 16 is simply INVISIBLE from the tile and can never
        # be collected. Watching the ground continuously is what showed it -
        # every sample capped at distance 13 while coins and bones sat on
        # screen further out.
        #
        # So step out to the spawns once a loot round, scan from there, and
        # come straight back. One short sortie per six attacks, not per shot.
        if pins and a.loot_sortie:
            cx = sum(q[0] for q in pins) // len(pins)
            cz = sum(q[1] for q in pins) // len(pins)
            walk.cli(
                a.character,
                "act",
                "walkTo",
                "--json",
                json.dumps({"x": cx, "z": cz, "running": True}),
            )
            walk.cli(a.character, "wait", "6")
            taken += sweep(a.character, takes, limit=10)
            if safespot:
                hold_safespot(a.character, safespot, tries=4)
        buried += bury_bones(a.character, state(a.character) or {})
        if safespot:
            hold_safespot(a.character, safespot, tries=4)
        atlas.observe(state(a.character))

        # Turn the valuables into Magic xp and coins rather than carrying them
        # home. Batched, because each batch swaps the bow out for the staff and
        # back, and that is only worth doing occasionally.
        if a.alch_every and r % a.alch_every == 0:
            alched += alch_valuables(a.character, a.alch_keep)

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
                attacks=kills,
                killed=killed,
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
