#!/usr/bin/env python3
"""The Karamja lobster circuit, as a recipe instead of a scratch file.

This loop has now been written twice and lost twice, which is the actual reason
it is here. It ran on 2026-09-12, took Fishing 81 to 99 and Cooking 85 to 99
across twelve laps, and lived in a session scratchpad that was wiped. The
knowledge survived as prose in a memory file; the working code did not.

What the loop is for has changed, and that is worth saying because it changes
what "enough" means. It used to be a Fishing and Cooking grind that happened to
pay for itself. It is now a **feedstock run**: a cooked lobster's config `cost`
is 150, so it high-alchs for 90 gp and **1,625 Magic xp**, against the 37-38 gp
a general store pays for it. Alchemy is the best experience tap this character
has and the only input it can run out of is the item. One lap is roughly 26
lobsters, so roughly 26 more high alchs.

    python3 recipes/circuit.py --character arete --laps 4

The legs, each verified against live state before the next begins:

    Falador bank (3013,3354)
      -> south down the x3007-3013 corridor, because Falador is walled and a
         single long walkTo cannot cross it
      -> Port Sarim, Captain Tobias (3024,3218), 30 gp, "Yes please."
      -> the ship: `player.level` reads 1 aboard and 0 ashore, which is the
         cheapest arrival check there is
      -> Karamja gangplank (2956,3144), option **Cross** -- not Open, which is
         why a walker that only probes for Gate/Door/Stile reports `stuck` on a
         perfectly good dock
      -> cage spots (2923-2926, 3179-3181), option Cage, lobster pot only
      -> Customs officer (2952,3146) to sail back. The dialogue BRANCHES:
         "Can I journey on this ship?", then "Search away, I have nothing to
         hide.", then "Ok." Sending option 1 blindly hits "Why?" and loops.
      -> Port Sarim gangplank (3031,3217), Cross
      -> Falador range (3036,3342), which is INSIDE a house: open the door at
         (3037,3347) from (3037,3348) first, or every attempt answers
         "I can't reach that!"
      -> bank (3013,3354)

Kit discipline, which is the part that gets skipped and costs the lap: a
gathering trip leaves with **only the tool and the fare**. 28 slots is the real
budget, and a pack that arrives full catches nothing. This checks what the
character is actually carrying before it decides what to do, because a lap that
died after a successful catch leaves her holding a full pack, and a naive
restart sails to Karamja with no room.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk  # noqa: E402

BANK_BOOTH = (2213, 3013, 3354)
RANGE_LOC = (3036, 3342)
RANGE_DOOR = (3037, 3347)
RANGE_DOOR_STAND = (3037, 3348)
TOBIAS = (3024, 3218)
CUSTOMS = (2952, 3146)
GANGPLANK_KARAMJA = (2956, 3144)
GANGPLANK_SARIM = (3031, 3217)
CAGE_SPOT = (2925, 3180)

# Falador is walled and its pathing is directional: southbound stalls at
# x~3024 z~3296 and northbound at x~3037 z~3270. The corridor that works is
# x3007-3013, and it is not optional.
TO_SARIM = [(3010, 3330), (3013, 3300), (3013, 3282), (3013, 3243), (3024, 3220)]
TO_FALADOR = [(3020, 3240), (3013, 3282), (3010, 3330), (3013, 3348)]


def emit(**kw):
    print(json.dumps(kw), flush=True)


def st(ch):
    return walk.state(ch) or {}


def inv_count(d, name):
    return sum(
        i.get("amount") or i.get("count") or 1
        for i in (d.get("inventory") or [])
        if i["name"] == name
    )


def slots(d):
    return len(d.get("inventory") or [])


def aboard(d):
    """1 on the ship, 0 ashore. The cheapest arrival check in the world."""
    return (d.get("player") or {}).get("level")


def cli(ch, *a):
    return walk.cli(ch, *a)


def act(ch, kind, **payload):
    out = cli(ch, "act", kind, "--json", json.dumps(payload))
    cli(ch, "wait", "3")
    return out


def goto(ch, waypoints, tol=3, min_hp=45):
    for wp in waypoints:
        walk.main(
            [
                "--character",
                ch,
                "--waypoints",
                "%d,%d" % wp,
                "--tol",
                str(tol),
                "--min-hp",
                str(min_hp),
            ]
        )


def bank_open(ch):
    lid, bx, bz = BANK_BOOTH
    for _ in range(3):
        act(ch, "interactLoc", locId=lid, x=bx, z=bz, optionIndex=2)
        cli(ch, "wait", "3")
        d = st(ch)
        if (d.get("bank") or {}).get("isOpen"):
            return d
    return None


def bank_slot(d, name):
    for i in (d.get("bank") or {}).get("items", []):
        if i["name"] == name:
            return i
    return None


def kit_up(ch, fare):
    """Leave with the tool and the fare, nothing else. 28 slots is the budget."""
    d = bank_open(ch)
    if not d:
        return False, "bank did not open"
    for i in list(d.get("inventory") or []):
        act(ch, "bankDeposit", slot=i["slot"], amount=10000)
    d = st(ch)
    for name, amt in (("Lobster pot", 1), ("Coins", fare)):
        row = bank_slot(d, name)
        if not row:
            act(ch, "closeModal")
            return False, "missing %s in bank" % name
        act(ch, "bankWithdraw", slot=row["slot"], amount=amt)
        d = st(ch)
    act(ch, "closeModal")
    d = st(ch)
    return (inv_count(d, "Lobster pot") >= 1 and inv_count(d, "Coins") > 0), "kitted"


def dialogue(ch, picks, rounds=10):
    """Answer a dialog by READING its options, never by always sending 1.

    Three details here are not guesses, they are `shop.py`'s and they were each
    paid for. Options carry their **own `index` field**; the position in the
    list is not it. A continuation page is `clickDialogOption` with
    **`optionIndex: 0`**. And an unmatched multi-option page is **left alone**
    rather than answered with a guess: the Customs officer branches, and
    clicking 1 blindly lands on "Why?" and loops through an explanation about
    imported spirits.

    `picks` is a list of substrings to match in order.
    """
    want = list(picks)
    for _ in range(rounds):
        d = st(ch)
        dlg = d.get("dialog") or {}
        if not dlg.get("isOpen"):
            break
        opts = dlg.get("options") or []
        clicked = False
        if want:
            for o in opts:
                text = str(o.get("text", "")).lower()
                if want[0].lower() in text:
                    act(ch, "clickDialogOption", optionIndex=o.get("index"))
                    emit(dialog_choice=o.get("text"))
                    want.pop(0)
                    clicked = True
                    break
        if clicked:
            continue
        if len(opts) > 1:
            emit(dialog_unanswered=[o.get("text") for o in opts])
            break
        # A continuation page. `shop.py` sends 0 here, and that works for the
        # shops it drives, but it is not universal: the Customs officer's
        # continue page reports a real option, `{"index": 1, "text": "Click
        # here to continue", "buttonType": 6}`. Send whatever index the server
        # actually reported, and only fall back to 0 when there is no option
        # at all.
        act(ch, "clickDialogOption", optionIndex=(opts[0].get("index") if opts else 0))
    return st(ch)


def npc_at(d, x, z, name_hint=None, radius=3):
    best = None
    for n in d.get("nearbyNpcs") or []:
        if name_hint and name_hint.lower() not in (n.get("name") or "").lower():
            continue
        dist = max(abs(n.get("x", 0) - x), abs(n.get("z", 0) - z))
        if dist <= radius and (best is None or dist < best[0]):
            best = (dist, n)
    return best[1] if best else None


def cross_gangplank(ch, x, z):
    """A ship is a place. The way off is a Cross, which is why a walker that
    probes for Gate/Door/Stile reports `stuck` on a perfectly good dock."""
    for _ in range(4):
        d = st(ch)
        for loc in d.get("nearbyLocs") or []:
            if "gangplank" not in (loc.get("name") or "").lower():
                continue
            opts = [o.get("text") for o in (loc.get("optionsWithIndex") or [])]
            if "Cross" in opts:
                act(
                    ch,
                    "interactLoc",
                    locId=loc["id"],
                    x=loc["x"],
                    z=loc["z"],
                    optionIndex=opts.index("Cross") + 1,
                )
                cli(ch, "wait", "5")
                return True
        goto(ch, [(x, z)], tol=2)
    return False


def sail(ch, npc_xz, name_hint, picks, want_level):
    """Board or leave, then confirm by `player.level` rather than by hope.

    The retry loop is the whole function. A first version answered the dialogue
    once and then polled for the level to change, and it stranded the character
    on Karamja with a full pack: the Customs officer's conversation ran past
    the answer budget, the dialog closed on a continuation page, and further
    clicks went nowhere because **a closed dialog cannot be advanced -- the NPC
    has to be talked to again, with the answers restarted from the top.**
    """
    goto(ch, [npc_xz], tol=3)
    for attempt in range(6):
        d = st(ch)
        if aboard(d) == want_level:
            return True, "sailed"
        dlg = d.get("dialog") or {}
        if not dlg.get("isOpen"):
            n = npc_at(d, npc_xz[0], npc_xz[1], name_hint, radius=6)
            if not n:
                goto(ch, [npc_xz], tol=3)
                continue
            opts = [o.get("text") for o in (n.get("optionsWithIndex") or [])]
            idx = (opts.index("Talk-to") + 1) if "Talk-to" in opts else 1
            act(ch, "interactNpc", npcIndex=n["index"], optionIndex=idx)
            cli(ch, "wait", "4")
        dialogue(ch, list(picks))
        cli(ch, "wait", "4")
    return False, "still level %s after 6 attempts" % aboard(st(ch))


def fish(ch, rounds=120):
    """Cage until the pack is full. XP per ATTEMPT is what matters, and the
    catch rate is poor, so most attempts return nothing and that is normal."""
    got0 = None
    for r in range(rounds):
        d = st(ch)
        if got0 is None:
            got0 = inv_count(d, "Raw lobster")
        if slots(d) >= 28:
            return inv_count(d, "Raw lobster") - got0, "pack full"
        spot = None
        for n in d.get("nearbyNpcs") or []:
            opts = [o.get("text") for o in (n.get("optionsWithIndex") or [])]
            if "Cage" in opts:
                spot = (n, opts.index("Cage") + 1)
                break
        if not spot:
            goto(ch, [CAGE_SPOT], tol=2)
            continue
        act(ch, "interactNpc", npcIndex=spot[0]["index"], optionIndex=spot[1])
        cli(ch, "wait", "8")
    d = st(ch)
    return inv_count(d, "Raw lobster") - (got0 or 0), "rounds spent"


def cook_all(ch):
    """The range is INSIDE a house. Open the door first or every attempt
    answers "I can't reach that!" from a tile that looks adjacent."""
    goto(ch, [RANGE_DOOR_STAND], tol=2)
    d = st(ch)
    for loc in d.get("nearbyLocs") or []:
        if loc.get("name") == "Door" and (loc["x"], loc["z"]) == RANGE_DOOR:
            act(
                ch,
                "interactLoc",
                locId=loc["id"],
                x=loc["x"],
                z=loc["z"],
                optionIndex=1,
            )
            break
    goto(ch, [RANGE_LOC], tol=2)
    cooked = 0
    for _ in range(40):
        d = st(ch)
        raw = [i for i in (d.get("inventory") or []) if i["name"] == "Raw lobster"]
        if not raw:
            break
        rng = None
        for loc in d.get("nearbyLocs") or []:
            if (
                "range" in (loc.get("name") or "").lower()
                or "stove" in (loc.get("name") or "").lower()
            ):
                rng = loc
                break
        if not rng:
            return cooked, "no range in reach"
        act(
            ch,
            "useItemOnLoc",
            slot=raw[0]["slot"],
            locId=rng["id"],
            x=rng["x"],
            z=rng["z"],
        )
        cli(ch, "wait", "6")
        dialogue(ch, ["All"], rounds=2)
        cli(ch, "wait", "20")
        cooked += 1
    # The door closes behind you, so the way out needs opening from the
    # inside as well. Skipping this leaves the character shut in a kitchen,
    # which reads from outside as a frozen session.
    for _ in range(4):
        d = st(ch)
        p = d.get("player") or {}
        if (p.get("worldZ") or 0) >= RANGE_DOOR_STAND[1]:
            break
        door = next(
            (
                loc
                for loc in (d.get("nearbyLocs") or [])
                if loc.get("name") == "Door" and (loc["x"], loc["z"]) == RANGE_DOOR
            ),
            None,
        )
        if door:
            act(
                ch,
                "interactLoc",
                locId=door["id"],
                x=RANGE_DOOR[0],
                z=RANGE_DOOR[1],
                optionIndex=1,
            )
        goto(ch, [(RANGE_DOOR_STAND[0], RANGE_DOOR_STAND[1] + 1)], tol=1)
    return cooked, "cooked"


def deposit_catch(ch):
    d = bank_open(ch)
    if not d:
        return 0
    n = 0
    for _ in range(40):
        d = st(ch)
        rows = [
            i
            for i in (d.get("inventory") or [])
            if i["name"] in ("Lobster", "Burnt lobster", "Raw lobster")
        ]
        if not rows:
            break
        act(ch, "bankDeposit", slot=rows[0]["slot"], amount=10000)
        n += 1
    act(ch, "closeModal")
    return n


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--laps", type=int, default=1)
    ap.add_argument("--fare", type=int, default=120, help="coins to carry per lap")
    a = ap.parse_args(argv)
    ch = a.character
    for lap in range(1, a.laps + 1):
        t0 = time.time()
        d = st(ch)
        emit(
            lap=lap,
            phase="start",
            at=[
                (d.get("player") or {}).get("worldX"),
                (d.get("player") or {}).get("worldZ"),
            ],
            slots=slots(d),
            raw=inv_count(d, "Raw lobster"),
            cooked=inv_count(d, "Lobster"),
        )
        ok, why = kit_up(ch, a.fare)
        if not ok:
            emit(lap=lap, stop="kit", why=why)
            return 1
        goto(ch, TO_SARIM)
        ok, why = sail(ch, TOBIAS, "Tobias", ["Yes please"], 1)
        if not ok:
            emit(lap=lap, stop="outbound boat", why=why)
            return 1
        cross_gangplank(ch, *GANGPLANK_KARAMJA)
        goto(ch, [CAGE_SPOT], tol=3)
        caught, why = fish(ch)
        emit(lap=lap, phase="fished", raw=caught, why=why)
        ok, why = sail(
            ch,
            CUSTOMS,
            "Customs",
            ["journey on this ship", "Search away", "Ok"],
            1,
        )
        if not ok:
            emit(lap=lap, stop="return boat", why=why)
            return 1
        cross_gangplank(ch, *GANGPLANK_SARIM)
        goto(ch, TO_FALADOR)
        cooked, why = cook_all(ch)
        banked = deposit_catch(ch)
        d = st(ch)
        emit(
            lap=lap,
            phase="done",
            raw_caught=caught,
            cooked=cooked,
            bank_calls=banked,
            minutes=round((time.time() - t0) / 60, 1),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
