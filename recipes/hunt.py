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

So the loop is one kill at a time:

    pick a target -> attack -> hold the tile until it is dead
        -> loot once (bones, arrows, valuables) -> bury -> alch -> repeat

That order is the whole design. An earlier version's round was one ATTACK,
and a moss giant takes about a dozen, so it never knew where the kill was and
grew a cadence flag for everything that had to happen after one: loot every N
rounds, alch every M, a sortie every so often. Every one of those was a guess
about where the kill was, and each guess produced its own silent failure --
looting mid-fight, alching mid-fight with the bow still on the ground, a
counter that never lined up with another counter. Making the kill explicit
removes the flags and the failures with them.

Two facts from the live measurement that the structure rests on, both from
the Ardougne moss giant camp on 2026-09-18:

  - **One `interactNpc` runs the whole fight.** Twelve hits landed over 36
    seconds from a single dispatch. So the fight loop attacks once and then
    only polls, re-attacking when the player's own combat block says the
    engagement dropped.
  - **The attack walks the character in, and the giant walks the rest.** One
    dispatch moved her four tiles off a safespot that costs nothing when
    held; HP went 99 to 65 in one kill. So the fight loop checks the tile on
    every poll and corrects a drift before anything else.

Measured over five kills with the tile held: 7.5 minutes, +30,400 Ranged xp,
4 of 5 big bones buried, HP 96 to 96, zero food eaten, arrows net positive.

    python3 recipes/hunt.py --character arete --npc "Moss giant" \
        --safespot 2546,3400 --target 2549,3408 --target 2554,3401 \
        --target 2554,3409 --weapon-range 10 --safe-pickup 12 \
        --min-hp 60 --food Salmon --kills 50

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
    # crowd out the drop that was worth the walk. Bones first: a kill leaves
    # ONE big bone and about a dozen arrow piles, and with arrows ranked
    # ahead the cap cut the bone off on the second kill of the 2026-09-18
    # trial. A bone is 375 Prayer xp; an arrow pile is a few gp and most of
    # them get collected anyway. Then ammunition, then the rest by value.
    # Ties break on distance so the cheap nearby pickups still happen on
    # the way.
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
        if any(k in n for k in BONES):
            tier = 0
        elif any(k in n for k in AMMO):
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
        # Exempting valuables from the radius was right and unbounded was not.
        # With no cap the sweep kept walking at drops it could not path to and
        # answering "I can't reach that!" round after round, which burned the
        # rounds that should have been shots: the xp rate fell to a fifth.
        # A valuable is worth extra tiles, never unlimited ones.
        if (
            within is not None
            and origin is not None
            and max(
                abs(item.get("x", 0) - origin[0]), abs(item.get("z", 0) - origin[1])
            )
            > within + 8
        ):
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
        if pickup(character, item):
            took += 1
        else:
            skipped.append((name, "not reached"))
    # Only worth saying when it went wrong: something on the ground that was
    # wanted and still not taken. A quiet sweep needs no commentary.
    if skipped or (seen and not took):
        emit(sweep_saw=len(seen), sweep_took=took, sweep_skipped=skipped[:6])
    return took


def stack_of(d, name):
    return sum(
        i.get("amount") or i.get("count") or 1
        for i in (d.get("inventory") or [])
        if i.get("name") == name
    )


def pickup(character, item, walks=3):
    """Walk until adjacent, pick up, and COUNT the item rather than the call.

    Drops land at the TARGET's feet, not yours, and `pickupItem` on something
    out of reach answers "I can't reach that!" with `success: true`. One
    `walkTo` covers 7 or 8 tiles, so a drop at 11 -- where a moss giant's big
    bones landed on 2026-09-18, inside the pickup radius -- was walked at once,
    not reached, and then counted as taken. Two of five bones went missing
    that way in one sample and the report said nothing. Now the walk repeats
    until the character is beside the drop, and the pickup is believed only
    when the inventory says so.
    """
    x, z, name = item.get("x"), item.get("z"), item.get("name")
    before = stack_of(walk.state(character) or {}, name)
    for _ in range(walks):
        d = walk.state(character) or {}
        p = d.get("player") or {}
        if max(abs(p.get("worldX", 0) - x), abs(p.get("worldZ", 0) - z)) <= 1:
            break
        walk.cli(
            character,
            "act",
            "walkTo",
            "--json",
            json.dumps({"x": x, "z": z, "running": True}),
        )
        walk.cli(character, "wait", "4")
    walk.cli(
        character,
        "act",
        "pickupItem",
        "--json",
        json.dumps({"x": x, "z": z, "itemId": item.get("id")}),
    )
    walk.cli(character, "wait", "2")
    return stack_of(walk.state(character) or {}, name) > before


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
    # Never a rune, of any kind. The owner's rule (2026-09-18): runes are for
    # casting, and the coins an alch returns do not buy them back. A chaos
    # rune high-alched for 9 coins the one time this list let it through.
    "rune",
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


def find_target(d, npc, pins, radius, weapon_range, safespot, idx=None):
    """The giant to shoot, or the one already being shot if `idx` is given.

    With `idx` this answers "is that exact creature still here and alive";
    without it, it picks a fresh one the same way the old loop did: matched
    by name, standing within `radius` of a pinned spawn, and within weapon
    range OF THE SAFESPOT rather than of wherever the character has drifted.
    """
    for n in d.get("nearbyNpcs") or []:
        if idx is not None:
            if n.get("index") != idx:
                continue
            if n.get("hp") is not None and n.get("hp", 1) <= 0:
                return None
            return n
        if (npc or "").lower() not in (n.get("name") or "").lower():
            continue
        if (n.get("hp") is not None) and n.get("hp", 1) <= 0:
            continue
        if pins and not any(
            max(abs(n.get("x", 0) - p[0]), abs(n.get("z", 0) - p[1])) <= radius
            for p in pins
        ):
            continue
        if weapon_range:
            origin = safespot or (
                (d.get("player") or {}).get("worldX"),
                (d.get("player") or {}).get("worldZ"),
            )
            if (
                max(abs(n.get("x", 0) - origin[0]), abs(n.get("z", 0) - origin[1]))
                > weapon_range
            ):
                continue
        return n
    return None


def skill_xp(d, name):
    for s in d.get("skills") or []:
        if s.get("name") == name:
            return s.get("experience", 0)
    return 0


def edible(d, food):
    return [i for i in d.get("inventory") or [] if i["name"] == food] or [
        i
        for i in d.get("inventory") or []
        if any((o.get("text") or "") == "Eat" for o in i.get("optionsWithIndex") or [])
    ]


def attack(character, target, option):
    r = walk.cli(
        character,
        "act",
        "interactNpc",
        "--json",
        json.dumps(
            {
                "npcIndex": target.get("index"),
                "optionIndex": option_index(target, option),
            }
        ),
    )
    # One tick, not several: the dispatch starts the character walking at the
    # target, and every tick before the fight loop pulls her back is a tick
    # inside the leash. Sample two on 2026-09-18 cost 18 HP over five kills
    # with a three-tick gap here.
    walk.cli(character, "wait", "1")
    return r


def fight(a, d, target, safespot, t_start):
    """Shoot one creature until it is dead, holding the tile the whole time.

    Measured on 2026-09-18 at the Ardougne camp: ONE `interactNpc` runs the
    whole fight. Twelve hits landed over 36 seconds from a single dispatch,
    +6,000 Ranged xp, and the giant died. So the loop here does not attack per
    round; it attacks once, then polls, and only re-attacks when the player's
    own combat block says the engagement dropped.

    What the same measurement also showed: the attack walked the character
    four tiles toward the target, and the giant walked the rest. HP 99 to 65
    in one kill from a tile that costs nothing when held. So every poll checks
    the tile first, and a drift is corrected before anything else.

    Death is unambiguous in the state: the target's `hp` reads 0, then its
    index is gone from `nearbyNpcs` on the next poll. Returns
    (killed, reason, d).
    """
    idx = target.get("index")
    x0 = skill_xp(d, a.xp_skill)
    last_xp, last_move = x0, time.time()
    shots = 0
    while True:
        p = d.get("player") or {}
        pos = (p.get("worldX"), p.get("worldZ"))
        # Death is a teleport: far from the start with full health.
        if abs(pos[0] - t_start[0]) + abs(pos[1] - t_start[1]) > 60:
            return False, "died and respawned", d
        if eat(a.character, d, a.min_hp, a.food):
            d = state(a.character) or d
        elif p.get("hp", 99) < a.min_hp and not edible(d, a.food):
            return False, "hurt with no food", d
        if safespot and pos != safespot:
            hold_safespot(a.character, safespot, tries=3)
            d = state(a.character) or d
            p = d.get("player") or {}
        tgt = find_target(d, a.npc, None, 0, 0, None, idx=idx)
        if tgt is None:
            return True, "killed", d
        if tgt.get("hp") == 0:
            walk.cli(a.character, "wait", "2")
            return True, "killed", state(a.character) or d
        c = p.get("combat") or {}
        if not c.get("inCombat") or c.get("targetIndex") != idx:
            if shots >= a.max_shots:
                return False, "target would not engage", d
            attack(a.character, tgt, a.option)
            shots += 1
        else:
            walk.cli(a.character, "wait", "3")
        d = state(a.character) or d
        xp_now = skill_xp(d, a.xp_skill)
        if xp_now != last_xp:
            last_xp, last_move = xp_now, time.time()
        elif time.time() - last_move > a.stall_seconds:
            return False, "no xp for %ds" % a.stall_seconds, d


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--npc", required=True, help="name, matched case-insensitively")
    ap.add_argument("--option", default="Attack")
    ap.add_argument("--take", action="append", default=[])
    ap.add_argument("--kills", type=int, default=100, help="stop after this many")
    ap.add_argument("--min-hp", type=int, default=45)
    ap.add_argument("--food", default="Lobster")
    ap.add_argument(
        "--safespot",
        default=None,
        help="x,z to hold for the whole fight; the tile the target cannot reach",
    )
    ap.add_argument(
        "--target",
        action="append",
        default=None,
        help="x,z of a SPAWN TILE to attack. Repeatable: (2546,3400) at the "
        "Ardougne moss giant camp covers three spawns at 8, 8 and 9 tiles.",
    )
    ap.add_argument(
        "--target-radius",
        type=int,
        default=5,
        help="how far from --target the pinned spawn may have wandered; "
        "default is a moss giant's maxrange of 5",
    )
    ap.add_argument(
        "--weapon-range",
        type=int,
        default=0,
        help="skip targets further than this from the safespot; 10 for a "
        "longbow, 7 for a shortbow. 0 disables the check",
    )
    ap.add_argument(
        "--safe-pickup",
        type=int,
        default=12,
        help="how far from the safespot the after-kill sweep will step for a "
        "drop. The corpse lands where the target stood, which at this camp is "
        "4 to 10 tiles out; measured 2026-09-17, 10 collected the corpse most "
        "kills and 16 quartered the kill rate",
    )
    ap.add_argument(
        "--alch",
        action="store_true",
        help="high-alch the valuables between kills. Off by default because "
        "the bow-restore after a staff swap failed once and left the "
        "character meleeing giants at Defence 1; the loop now STOPS if the "
        "weapon is not a bow afterwards, but turn it on only while watching",
    )
    ap.add_argument("--alch-keep", type=int, default=10)
    ap.add_argument(
        "--xp-skill",
        default="Ranged",
        help="the skill a fight must keep moving; a fight that stops moving it "
        "for --stall-seconds is abandoned and a target re-picked",
    )
    ap.add_argument("--stall-seconds", type=int, default=45)
    ap.add_argument(
        "--max-shots",
        type=int,
        default=6,
        help="attack dispatches per fight before giving up on that target",
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

    # Read the WEAPON, not the quiver: a run that began with an empty quiver
    # and 56 arrows in the pack once decided it was a melee camp and fired
    # nothing for five minutes.
    def weapon_name(d):
        return next(
            (
                (e.get("name") or "").lower()
                for e in (d.get("equipment") or [])
                if e.get("slot") == 3
            ),
            "",
        )

    ranged_camp = any(w in weapon_name(d) for w in ("bow", "crossbow", "sling", "dart"))
    start = counts(d)
    xp0 = {s["name"]: s.get("experience", 0) for s in d.get("skills") or []}
    t0 = time.time()
    kills = fights = taken = buried = alched = 0

    p = d.get("player") or {}
    hp, maxhp = p.get("hp", 0), p.get("maxHp", 0) or 1
    here0 = (p.get("worldX"), p.get("worldZ"))

    # Never open a fight already hurt: sent in at 52/94 against level 42
    # giants at Defence 1, dead before the first log line.
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

    emit(hunt="start", npc=a.npc, take=takes, hp=hp, of=maxhp, alch=a.alch)

    def report(d, **extra):
        now = counts(d)
        gained = {
            k: now.get(k, 0) - start.get(k, 0)
            for k in set(now) | set(start)
            if now.get(k, 0) - start.get(k, 0) > 0
        }
        xp = {
            s["name"]: s.get("experience", 0) - xp0.get(s["name"], 0)
            for s in d.get("skills") or []
            if s.get("experience", 0) - xp0.get(s["name"], 0) > 0
        }
        emit(
            kills=kills,
            fights=fights,
            picked_up=taken,
            bones_buried=buried,
            alched=alched,
            hp=(d.get("player") or {}).get("hp"),
            food=len(edible(d, a.food)),
            free_slots=28 - len(d.get("inventory") or []),
            xp=xp,
            gained=gained,
            minutes=round((time.time() - t0) / 60, 1),
            **extra,
        )

    reason = "kill cap"
    idle = 0
    while kills < a.kills:
        d = state(a.character)
        if not d:
            reason = "lost the session"
            break
        if not edible(d, a.food):
            reason = "out of food"
            break
        if ranged_camp and not rewield_ammo(a.character, d):
            reason = "out of ammunition"
            break
        d = state(a.character) or d
        if safespot and not hold_safespot(a.character, safespot, tries=4):
            emit(warn="not on the safespot", at=(walk.settled(a.character)[0]))
            d = state(a.character) or d

        target = find_target(d, a.npc, pins, a.target_radius, a.weapon_range, safespot)
        if target is None:
            idle += 1
            if idle % 6 == 0:
                emit(note="no target in range", idle_polls=idle)
            walk.cli(a.character, "wait", "5")
            continue
        idle = 0

        # 1. Attack, and stay on the tile until it is dead.
        fights += 1
        attack(a.character, target, a.option)
        killed, why, d = fight(a, state(a.character) or d, target, safespot, here0)
        if why == "died and respawned":
            reason = why
            break
        if why == "hurt with no food":
            reason = why
            break
        if not killed:
            emit(fight="abandoned", reason=why, target=target.get("index"))
            continue
        kills += 1

        # 2. Loot, once, now that nothing alive is on the tile. Arrows first,
        #    then bones, then the rest by value; `sweep` ranks them.
        origin = safespot or (
            (d.get("player") or {}).get("worldX"),
            (d.get("player") or {}).get("worldZ"),
        )
        taken += sweep(
            a.character, takes, limit=10, within=a.safe_pickup, origin=origin
        )
        # 3. Bury, then get back on the tile before the respawn.
        buried += bury_bones(a.character, state(a.character) or {})
        if safespot:
            hold_safespot(a.character, safespot, tries=4)
        d = state(a.character) or d
        atlas.observe(d)

        # 4. Alch between kills, standing safe with nothing to shoot. Then
        #    CHECK the weapon, and stop rather than fight with a staff.
        if a.alch:
            alched += alch_valuables(a.character, a.alch_keep)
            d = state(a.character) or d
            if ranged_camp and "bow" not in weapon_name(d):
                reason = "weapon not restored after alching"
                emit(hunt="stopped", reason=reason, weapon=weapon_name(d))
                break

        report(d, fight_shots=None)

    d = state(a.character) or {}
    report(d, hunt="done", reason=reason)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
