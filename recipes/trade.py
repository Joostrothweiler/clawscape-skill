#!/usr/bin/env python3
"""Move items between two characters through the real trade interface.

`deliver.py` + `collect.py` do a handoff by dropping on the floor, and that
works only when the pickup is immediate: **dropped items despawn on a timer**
(confirmed live -- a 10-Mind-rune cache dropped for a later pickup was simply
gone). Anything valuable, or any handoff where the two characters are not
already standing together, needs a real trade.

Run it on BOTH sides at about the same time. One action runs per character, so
one process can never drive both halves -- and it does not need to: the trade
screen itself is the synchronisation channel. Each side reads `state trade`,
decides the single next thing its own character owes the exchange, and does
it. The giver names what it is handing over; the receiver names nothing:

    # giver
    uv run recipes/trade.py --character oakward --with Sylas \\
        --give 558 --give 556

    # receiver, started at about the same time
    uv run recipes/trade.py --character sylas --with Oakward

## The protocol, and the two ways it silently does nothing

The component ids come from references/mechanics.md, which verified the
sequence live. Both traps below report `success: true` while transferring
nothing, which is why every step here is confirmed by reading state back
rather than by trusting a dispatch result:

1. `interactPlayer` from both sides, then wait for `modalInterface` **3323**.
   Nearby players carry **no option list**, so the right `optionIndex` cannot
   be read out of state and the CLI cannot echo the label back -- the menu is
   built per target, and the same index that opens a trade with one player
   starts a fight with the next. So the index is *probed*: send one, read the
   modal back, try the next on failure. **This is the first trap** -- a run
   that never opened a trade looks exactly like one that did, and steps 2-4
   then click components on a screen that is not there, each reporting
   success. Nothing proceeds here until 3323 is actually observed.
2. The giver places each stack: `clickComponentWithOption` on component
   **3322** (the trade-side inventory) with the inventory `slot` and an
   `optionIndex` from *that component's* own menu -- **1 offers one item, 4
   offers the whole stack**, both confirmed live. `--offer-option` defaults to
   4, because the first live run used 1 and moved a single coin out of 435
   while reporting a perfectly clean trade. Re-derive slots after every
   placement -- they shift as items move into the offer.
3. Both send `clickComponent` **3420** to accept, then wait for
   `modalInterface` **3443**, the confirm screen.
4. Both send `clickComponent` **3546** to confirm. **This is the second
   trap** -- items only move here, and a trade abandoned on the confirm
   screen moves nothing while both sides show as having accepted.

Output is one JSON object per line: a `round` line per poll carrying the
screen and both offers, a `placed` line per stack offered, then a final `done`
line naming why it stopped. Exit status is 0 when the expected items actually
changed hands (verified against the receiving inventory), 2 when it stopped
early (partner never appeared, the screen never opened, a timeout, low HP),
and 1 for a usage or world error.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from travel import (  # noqa: E402
    Stop,
    act,
    cli,
    emit,
    read_state,
    wait,
)


# deliver.py has equivalents of the next two, but this recipe deliberately does
# not import them: dropping and trading are alternative answers to the same
# job, and making the trade path depend on the drop path would mean you cannot
# have one without the other.
def find_player(character: str, name: str):
    """Look up a named player in the current scene via `state players`."""
    result = cli(character, "state", "players", "--name", name)
    for player in result.get("players") or []:
        if player.get("name", "").lower() == name.lower():
            return player
    return None


def matching_slots(state: dict, wanted: list) -> list:
    """Inventory rows whose item id or name (substring, case-insensitive)
    matches any entry in `wanted`. Re-derive after every placement -- slots
    shift as items move into the offer.
    """
    ids = {w for w in wanted if w.isdigit()}
    names = [w.lower() for w in wanted if not w.isdigit()]
    rows = []
    for item in state.get("inventory") or []:
        item_id = str(item.get("id"))
        item_name = str(item.get("name", "")).lower()
        if item_id in ids or any(n in item_name for n in names):
            rows.append(item)
    return rows


MAIN_SCREEN = 3323
OFFER_COMPONENT = 3322
# The trade-side inventory's own option menu, confirmed live by transferring a
# coin stack at each index: 1 offers ONE item, 4 offers the WHOLE stack. 4 is
# the default because a handoff almost always means "all of it", and an
# unnoticed Offer-1 is the quiet version of this recipe failing -- the first
# live run of it moved a single coin out of 435 and reported a clean success.
OFFER_ALL_OPTION = 4
ACCEPT_COMPONENT = 3420
CONFIRM_SCREEN = 3443
CONFIRM_COMPONENT = 3546

# Players expose no option list, so the trade index has to be probed. 4 opened
# a trade with a party member in the one case anyone recorded; the rest are
# tried in a stable order so two sides probing at once converge instead of
# chasing each other.
DEFAULT_OPTIONS = [4, 3, 2, 5, 1]


def trade_of(state: dict) -> dict:
    return state.get("trade") or {}


def modal_of(state: dict) -> int:
    value = state.get("modalInterface")
    return value if isinstance(value, int) else -1


def counts(state: dict, wanted: list) -> dict:
    """How many of each wanted item this character is holding right now."""
    held = {}
    for item in state.get("inventory") or []:
        item_id = str(item.get("id"))
        name = str(item.get("name", "")).lower()
        for want in wanted:
            if want.isdigit():
                if item_id == want:
                    held[want] = held.get(want, 0) + (item.get("count") or 1)
            elif want.lower() in name:
                held[want] = held.get(want, 0) + (item.get("count") or 1)
    return held


def offered_ids(offer) -> set:
    out = set()
    for row in offer or []:
        if isinstance(row, dict):
            if row.get("id") is not None:
                out.add(str(row["id"]))
            if row.get("name"):
                out.add(str(row["name"]).lower())
    return out


def still_to_place(state: dict, wanted: list) -> list:
    """Slots holding a wanted item that is not already in my offer."""
    already = offered_ids(trade_of(state).get("myOffer"))
    pending = []
    for want in wanted:
        if want.isdigit() and want in already:
            continue
        if not want.isdigit() and any(want.lower() in a for a in already):
            continue
        pending.extend(matching_slots(state, [want]))
    # Deduplicate slots while keeping order; a stack matched by both id and
    # name must not be offered twice.
    seen, unique = set(), []
    for slot in pending:
        key = slot if isinstance(slot, int) else slot.get("slot")
        if key in seen:
            continue
        seen.add(key)
        unique.append(slot)
    return unique


def slot_number(slot) -> int:
    return slot if isinstance(slot, int) else slot.get("slot")


def guard(state: dict, args) -> None:
    player = state.get("player") or {}
    if player.get("isDead"):
        raise Stop("died", "inventory is lost on death; re-equip before resuming")
    hp = player.get("hp")
    if isinstance(hp, int) and hp <= args.min_hp:
        raise Stop("low_hp", "hp %s at or under --min-hp %s" % (hp, args.min_hp))


def open_the_screen(args, state: dict, tried: list) -> None:
    """Probe one interactPlayer option index, since players carry no menu."""
    partner = find_player(args.character, args.partner)
    if partner is None:
        raise Stop(
            "partner_not_visible",
            "%s is not in this scene; both characters must be standing together "
            "before either can open a trade" % args.partner,
        )
    remaining = [o for o in args.options if o not in tried]
    if not remaining:
        raise Stop(
            "no_trade_option",
            "every option index %s was tried against %s and none opened "
            "modalInterface %d; read the game messages to see what they did "
            "open instead" % (args.options, args.partner, MAIN_SCREEN),
        )
    option = remaining[0]
    tried.append(option)
    result = act(
        args.character,
        "interactPlayer",
        {"playerIndex": partner.get("index"), "optionIndex": option},
    )
    emit(
        {
            "probing": option,
            "partnerIndex": partner.get("index"),
            "success": result.get("success"),
            "reason": result.get("reason"),
        }
    )


def run(args) -> str:
    wanted = [str(w) for w in args.give]
    args.expect = [str(e) for e in args.expect]
    opening = read_state(args.character)
    before = counts(opening, wanted) if wanted else {}
    expected_before = counts(opening, args.expect) if args.expect else {}
    tried: list = []
    accepted_main = False
    confirmed = False

    for round_number in range(1, args.max_rounds + 1):
        state = read_state(args.character)
        guard(state, args)
        trade = trade_of(state)
        modal = modal_of(state)

        emit(
            {
                "round": round_number,
                "modal": modal,
                "isOpen": trade.get("isOpen"),
                "screen": trade.get("screen"),
                "partner": trade.get("partner"),
                "myOffer": trade.get("myOffer"),
                "theirOffer": trade.get("theirOffer"),
                "myAccepted": trade.get("myAccepted"),
                "partnerAccepted": trade.get("partnerAccepted"),
            }
        )

        # --- finished? Only an inventory delta proves a transfer. -----------
        if confirmed and modal != CONFIRM_SCREEN and modal != MAIN_SCREEN:
            fresh = read_state(args.character)
            if wanted:
                after = counts(fresh, wanted)
                gone = {k: before.get(k, 0) - after.get(k, 0) for k in wanted}
                if any(v > 0 for v in gone.values()):
                    emit({"handed_over": gone})
                    return "traded"
                raise Stop(
                    "nothing_moved",
                    "the screens completed but %s still holds %s; the offer "
                    "was probably never placed" % (args.character, after),
                )
            if args.expect:
                # The receiving side has to check too. Both sides clicking
                # through every screen is exactly the state a trade abandoned
                # on the confirm screen leaves behind, and it moves nothing.
                after = counts(fresh, args.expect)
                gained = {
                    k: after.get(k, 0) - expected_before.get(k, 0) for k in args.expect
                }
                if any(v > 0 for v in gained.values()):
                    emit({"received": gained})
                    return "traded"
                raise Stop(
                    "nothing_arrived",
                    "the screens completed but %s gained none of %s; ask the "
                    "giver whether its offer was ever placed"
                    % (args.character, args.expect),
                )
            # Nothing to give and nothing named to expect: the screens
            # completed, which is all this side can honestly claim.
            return "screens_completed"

        # --- step 4: confirm screen ----------------------------------------
        if modal == CONFIRM_SCREEN:
            if not confirmed:
                result = act(
                    args.character,
                    "clickComponent",
                    {"componentId": CONFIRM_COMPONENT},
                )
                confirmed = True
                emit({"confirmed": CONFIRM_COMPONENT, "success": result.get("success")})
            wait(args.character, args.ticks)
            continue

        # --- steps 2 and 3: main screen ------------------------------------
        if modal == MAIN_SCREEN:
            pending = still_to_place(state, wanted) if wanted else []
            if pending:
                slot = slot_number(pending[0])
                result = act(
                    args.character,
                    "clickComponentWithOption",
                    {
                        "componentId": OFFER_COMPONENT,
                        "optionIndex": args.offer_option,
                        "slot": slot,
                    },
                )
                emit(
                    {
                        "placed": slot,
                        "success": result.get("success"),
                        "reason": result.get("reason"),
                    }
                )
                accepted_main = False  # changing the offer resets both accepts
                wait(args.character, args.ticks)
                continue
            if not accepted_main:
                result = act(
                    args.character,
                    "clickComponent",
                    {"componentId": ACCEPT_COMPONENT},
                )
                accepted_main = True
                emit({"accepted": ACCEPT_COMPONENT, "success": result.get("success")})
            wait(args.character, args.ticks)
            continue

        # --- step 1: no screen yet -----------------------------------------
        if trade.get("isOpen"):
            # The section says open while the modal has not arrived; give the
            # world a tick rather than clicking into nothing.
            wait(args.character, args.ticks)
            continue
        if confirmed or accepted_main:
            # The screen went away mid-exchange: the partner walked off or
            # declined. Treat a vanished screen as an outcome, not a retry.
            raise Stop(
                "screen_closed",
                "the trade screen closed before it completed; nothing is "
                "guaranteed to have moved -- read the inventory back",
            )
        open_the_screen(args, state, tried)
        wait(args.character, args.ticks)

    raise Stop("max_rounds", "%d rounds without completing a trade" % args.max_rounds)


def parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move items between two characters through the trade interface."
    )
    parser.add_argument("--character", required=True)
    parser.add_argument(
        "--with",
        dest="partner",
        required=True,
        help="The other character's name; it must be in this scene",
    )
    parser.add_argument(
        "--give",
        action="append",
        default=[],
        help="Item id or name substring to hand over, repeatable. Omit "
        "entirely on the receiving side.",
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help="Item id or name substring the RECEIVING side should end up "
        "holding more of, repeatable. Without it a receiver can only report "
        "that the screens completed, which a trade abandoned on the confirm "
        "screen also does.",
    )
    parser.add_argument(
        "--offer-option",
        type=int,
        default=OFFER_ALL_OPTION,
        help="optionIndex on the trade-side inventory when placing a stack. "
        "Confirmed live: 1 = Offer-1, 4 = Offer-All (the default). Anything "
        "that offers fewer than the whole stack still reports a clean trade, "
        "so check the handed_over/received line rather than the exit status.",
    )
    parser.add_argument(
        "--option",
        dest="options",
        action="append",
        type=int,
        help="interactPlayer option index to probe, repeatable and tried in "
        "order. Players carry no option list, so this is a probe.",
    )
    parser.add_argument("--ticks", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=40)
    parser.add_argument("--min-hp", type=int, default=0, help="Stop at or under this")
    args = parser.parse_args(argv)
    if not args.options:
        args.options = list(DEFAULT_OPTIONS)
    return args


def main(argv) -> int:
    args = parse(argv)
    try:
        outcome = run(args)
    except Stop as stop:
        emit({"done": stop.reason, "detail": stop.detail})
        return 1 if stop.reason in ("no_state", "cli_unreadable") else 2
    except KeyboardInterrupt:
        emit({"done": "interrupted", "detail": "the trade screen may still be open"})
        return 2
    emit({"done": outcome})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
