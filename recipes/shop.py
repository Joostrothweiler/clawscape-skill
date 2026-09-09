#!/usr/bin/env python3
"""Explore a list of waypoints looking for a shop, and buy from it if found.

There is no merchant directory in this world (mechanics.md's "Shops"
section): finding one means exploring, or asking on the forum/chat. Doing
that by hand costs an agent a full observe-decide-act exchange per waypoint,
on top of the travel itself, and a promising direction found by one character
is otherwise lost the moment its context ends.

This runs the search as a script: visit each `--waypoint` in turn (via
`travel.py`), and at each stop check every nearby NPC's own option menu for
something that opens a shop (`--npc-option`, matched by substring,
case-insensitive; default covers "trade" and "shop"). The first NPC that
matches gets `interactNpc`'d; once `state shop` reports `isOpen`, its stock is
matched against `--buy` filters and bought with `shopBuy`, spending down to
`--reserve-coins`. On success the waypoint is saved to `--routes` under
`--landmark` (if given) so the next character can `travel.py --landmark
NAME` straight there instead of re-exploring.

    uv run recipes/shop.py --character gorruk \\
        --waypoint 3120,3220 --waypoint 3100,3200 --waypoint 3080,3230 \\
        --buy "Mind rune" --buy "Air rune" --reserve-coins 20 \\
        --landmark rune_shop

Output is one JSON object per step -- travel checkpoints (see travel.py), a
`checking` line per waypoint, a `bought` line per purchase -- then a final
`done` line naming why it stopped. Exit status is 0 when at least one item
was bought, 2 when no shop (or no matching stock) turned up after every
waypoint, 1 on a usage or world error.

This does NOT replace asking around -- a shop an NPC or forum post already
named is a known destination for `travel.py`/`deliver.py`, not something to
re-discover by wandering. Use this when nothing has been found yet and a
genuinely new direction is worth covering.
"""

from __future__ import annotations

import argparse
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from travel import (  # noqa: E402
    DEFAULT_ROUTES,
    Stop,
    act,
    cli,
    emit,
    load_routes,
    pos_of,
    read_state,
    travel,
    update_routes,
    wait,
)


def find_shop_npc(state: dict, option_terms: list):
    """The nearest reachable NPC whose own menu offers a shop-opening option."""
    terms = [t.lower() for t in option_terms]
    found = []
    for row in state.get("nearestNpcs") or state.get("nearbyNpcs") or []:
        if row.get("reachable") is False:
            continue
        for entry in row.get("optionsWithIndex") or []:
            text = str(entry.get("text", "")).lower()
            if any(term in text for term in terms):
                found.append((row.get("distance", 10**9), row, entry))
                break
    if not found:
        return None
    found.sort(key=lambda item: item[0])
    _, row, entry = found[0]
    return row, entry


# Shops opened by Talk-to rather than a Trade option need a dialogue answer.
# Aubury's is "Yes please!"; the others are guesses that cost nothing to try.
DEFAULT_DIALOG_CHOICES = ["yes please", "yes, please", "can i buy", "trade", "buy"]


def advance_dialog(character: str, state: dict, choices: list) -> bool:
    """Click through a dialogue that stands between an NPC and its shop.

    Not every shop opens from its own menu. Aubury's Rune Shop is `Talk-to`
    followed by a "Yes please!" choice -- there is no Trade option on him at
    all -- so a search that only matches shop-ish option text walks straight
    past the one shop that matters. Confirmed against the server's own
    content: `[opnpc1,aubury]` leads to `@multi2("Yes please!", aubury_shop)`
    and only then `~openshop_activenpc`.

    Returns True if it clicked something, so the caller polls again.
    """
    dialog = state.get("dialog") or {}
    if not dialog.get("isOpen"):
        return False
    options = dialog.get("options") or []
    terms = [c.lower() for c in (choices or DEFAULT_DIALOG_CHOICES)]
    for option in options:
        text = str(option.get("text", "")).lower()
        if any(term in text for term in terms):
            # `state dialog` numbers choices from 1 and calls the field
            # `index`; the action field is `optionIndex`.
            index = option.get("index")
            act(character, "clickDialogOption", {"optionIndex": index})
            emit({"dialog_choice": option.get("text"), "optionIndex": index})
            return True
    if len(options) > 1:
        # A real question this recipe was not told how to answer. Clicking a
        # guess here could sell something or accept a quest.
        emit({"dialog_unanswered": [o.get("text") for o in options]})
        return False
    # A single-option or optionless page is a continuation; 0 means continue.
    act(character, "clickDialogOption", {"optionIndex": 0})
    return True


# One stock line should never need more calls than this; it is a guard against
# looping on a shelf that reports success and delivers nothing.
MAX_BUY_CALLS = 40
# Observed cap: one shopBuy delivers at most this many units, whatever it is
# asked for.
BUY_BATCH = 10


def inventory_full_of(state: dict) -> bool:
    return len(state.get("inventory") or []) >= 28


def held_count(state: dict, name) -> int:
    """How many of a named item the character is holding right now."""
    if not name:
        return 0
    wanted = str(name).lower()
    total = 0
    for item in state.get("inventory") or []:
        if wanted in str(item.get("name", "")).lower():
            total += item.get("count") or 1
    return total


def matching_stock(shop_items: list, wanted: list):
    names = [w.lower() for w in wanted]
    hits = []
    for item in shop_items:
        name = str(item.get("name", "")).lower()
        if any(w in name for w in names):
            hits.append(item)
    return hits


def stock_price(item: dict):
    for key in ("buyPrice", "price", "cost", "value"):
        if isinstance(item.get(key), int):
            return item[key]
    return None


def stock_count(item: dict):
    for key in ("count", "stock", "amount", "quantity"):
        if isinstance(item.get(key), int):
            return item[key]
    return None


def coins_of(state: dict):
    for row in state.get("inventory") or []:
        if row.get("id") == 995:
            return row.get("count", 0)
    return 0


def travel_args(args, x, z):
    return SimpleNamespace(
        character=args.character,
        landmark=None,
        x=x,
        z=z,
        routes=args.routes,
        hop_size=args.hop_size,
        ticks=args.ticks,
        max_rounds=args.max_rounds,
        patience=args.patience,
        probe_radius=args.probe_radius,
        min_hp=args.min_hp,
    )


def try_buy_here(character: str, args, waypoint) -> list:
    """Look for a shop NPC at the current spot and buy matching stock.

    Returns a list of {name, amount, spent} dicts, empty if no shop was found
    or nothing on its shelves matched --buy.
    """
    state = read_state(character)
    hit = find_shop_npc(state, args.npc_option)
    if not hit:
        return []
    row, entry = hit
    emit({"checking": row.get("name"), "at": waypoint, "option": entry.get("text")})
    act(
        character,
        "interactNpc",
        {"npcIndex": row["index"], "optionIndex": entry["opIndex"]},
    )
    shop = {}
    # More rounds than the plain case needs: a dialogue-gated shop spends some
    # of them clicking through pages before the shop can even appear.
    for _ in range(14):
        wait(character, 2)
        state = read_state(character)
        shop = state.get("shop") or {}
        if shop.get("isOpen"):
            break
        if advance_dialog(character, state, args.dialog_choice):
            continue
    if not shop.get("isOpen"):
        emit({"shop_did_not_open": row.get("name")})
        return []

    emit(
        {
            "shop_open": shop.get("title"),
            "stock": [i.get("name") for i in shop.get("shopItems") or []],
        }
    )
    hits = matching_stock(shop.get("shopItems") or [], args.buy)
    purchases = []
    if hits:
        budget = coins_of(state) - args.reserve_coins
        # ROUND-ROBIN across the shelves, not one shelf to exhaustion. Buying
        # each line to its limit in turn spent an entire 406-coin budget on
        # Air runes and left the caster with 90 Air and 10 Mind -- and Wind
        # Strike needs one of each, so that stock was worth 10 casts, not 100.
        # A spell's runes are only useful in ratio, so the purchase has to be
        # balanced. One capped batch per line per round does that without
        # needing to know the recipe.
        got = {item.get("name"): 0 for item in hits}
        spent = {item.get("name"): 0 for item in hits}
        for _round in range(MAX_BUY_CALLS):
            if budget <= 0:
                break
            progressed = False
            for item in hits:
                name = item.get("name")
                price = stock_price(item)
                if got[name] >= args.amount or budget <= 0:
                    continue
                if isinstance(price, int) and price > 0 and budget < price:
                    continue
                # shopBuy CAPS AT ~10 UNITS PER CALL whatever is asked for:
                # one call requesting 116 Air runes returned success, logged
                # the request, and delivered 10. And it reports dispatch, not
                # effect, so the only evidence is the inventory.
                before = read_state(character)
                before_held = held_count(before, name)
                before_coins = coins_of(before)
                ask = min(args.amount - got[name], BUY_BATCH)
                act(character, "shopBuy", {"slot": item.get("slot"), "amount": ask})
                wait(character, 2)
                after = read_state(character)
                arrived = held_count(after, name) - before_held
                paid = before_coins - coins_of(after)
                if arrived > 0:
                    got[name] += arrived
                    spent[name] += max(0, paid)
                    budget -= max(0, paid)
                    progressed = True
                if inventory_full_of(after):
                    emit({"pack_full": name, "held": got[name]})
                    budget = 0
                    break
            if not progressed:
                break
        for name in got:
            emit({"bought": name, "received": got[name], "spent": spent[name]})
            if got[name] > 0:
                purchases.append(
                    {"name": name, "amount": got[name], "spent": spent[name]}
                )

    cli(character, "act", "closeShop", "--json", "{}")
    return purchases


def shop(args) -> str:
    routes = load_routes(args.routes)
    waypoints = list(args.waypoint)
    if args.landmark:
        known = (routes.get("landmarks") or {}).get(args.landmark)
        if known and tuple(known) not in waypoints:
            emit({"known_landmark": args.landmark, "pos": known, "trying_first": True})
            waypoints = [tuple(known)] + waypoints
    all_purchases = []
    for waypoint in waypoints:
        x, z = waypoint
        outcome = travel(travel_args(args, x, z))
        if outcome != "arrived":
            emit({"waypoint_unreachable": [x, z], "reason": outcome})
            continue
        purchases = try_buy_here(args.character, args, [x, z])
        if purchases:
            all_purchases.extend(purchases)
            if args.landmark:
                pos = list(pos_of(read_state(args.character)))
                update_routes(
                    args.routes,
                    lambda r: r.setdefault("landmarks", {}).__setitem__(
                        args.landmark, pos
                    ),
                )
                emit({"landmark_saved": args.landmark, "pos": pos})
            return "shop_found"

    if not all_purchases:
        raise Stop(
            "no_shop_found",
            "checked %d waypoint(s), none had a %r NPC selling %r"
            % (len(args.waypoint), args.npc_option, args.buy),
        )
    return "shop_found"


def parse_point(text: str):
    x, z = text.split(",")
    return int(x), int(z)


def parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visit waypoints looking for a shop, and buy matching stock if found."
    )
    parser.add_argument("--character", required=True)
    parser.add_argument(
        "--waypoint",
        action="append",
        required=True,
        type=parse_point,
        metavar="X,Z",
        help="A spot to check, as X,Z (repeatable, visited in order)",
    )
    parser.add_argument(
        "--buy",
        action="append",
        default=[],
        help="Item name substring to buy if a shop is found (repeatable)",
    )
    parser.add_argument(
        "--dialog-choice",
        action="append",
        default=None,
        help="Dialogue option text (substring) that leads to the shop, for a "
        "shop opened by Talk-to rather than a Trade option -- Aubury's is "
        '"Yes please!". Repeatable. Continuation pages are clicked through '
        "automatically.",
    )
    parser.add_argument(
        "--npc-option",
        action="append",
        default=["trade", "shop"],
        help='NPC menu text substring that means "this opens a shop" (repeatable)',
    )
    parser.add_argument(
        "--amount", type=int, default=200, help="Max units to buy per stock line"
    )
    parser.add_argument(
        "--reserve-coins", type=int, default=0, help="Coins to never spend"
    )
    parser.add_argument(
        "--landmark", help="Save the shop's spot in --routes under this name"
    )
    parser.add_argument("--routes", default=DEFAULT_ROUTES, help="Path to routes.json")
    parser.add_argument(
        "--hop-size", type=int, default=7, help="Tiles per walkTo call (travel legs)"
    )
    parser.add_argument(
        "--ticks", type=int, default=4, help="Ticks per hop (travel legs)"
    )
    parser.add_argument(
        "--max-rounds", type=int, default=150, help="Per-leg travel round cap"
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=3,
        help="Stuck rounds to allow before giving up a leg",
    )
    parser.add_argument(
        "--probe-radius",
        type=int,
        default=15,
        help="Tiles to search for a crossing or sidestep opening",
    )
    parser.add_argument("--min-hp", type=int, default=5, help="Stop at or under this")
    args = parser.parse_args(argv)
    if not args.dialog_choice:
        args.dialog_choice = list(DEFAULT_DIALOG_CHOICES)
    return args


def main(argv) -> int:
    args = parse(argv)
    try:
        outcome = shop(args)
    except Stop as stop:
        emit({"done": stop.reason, "detail": stop.detail})
        return 1 if stop.reason in ("cli_unreadable", "no_state") else 2
    except KeyboardInterrupt:
        emit({"done": "interrupted", "detail": "the character keeps its last action"})
        return 2
    emit({"done": outcome})
    return 0 if outcome == "shop_found" else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
