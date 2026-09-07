#!/usr/bin/env python3
"""Train one skill by repeating one interaction, and stop when it matters.

A grind is a loop, and an agent driving it a tick at a time pays for every
round in context: pick a target, act, wait, read, decide, repeat. This runs
the loop as a script and reports one line per round, so the agent reads
checkpoints instead of ticks.

    uv run recipes/train.py --character gorruk --npc goblin --option Attack \
        --skill Attack --target-level 20

    uv run recipes/train.py --character gorruk --loc tree --option "Chop down" \
        --skill Woodcutting --target-level 15 --ticks 8

Output is one JSON object per line: a checkpoint per round, then a final
`done` line naming why it stopped. Exit status is 0 when the target level was
reached, 2 when it stopped for another reason, 1 on a usage or world error.

It stops on: the target level, a dialog needing a real choice, death, HP under
--min-hp, a full inventory, no target in range, no experience for --patience
rounds, or --max-rounds. Continuation dialogs (the level-up page) are cleared
automatically, because they block every action that follows.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

CLI = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "clawscape.py")
)


class Stop(Exception):
    """The loop is over; `reason` says why, in one machine-readable word."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def cli(character: str, *words: str) -> dict:
    """Run one CLI command and parse its JSON, whatever its exit status."""
    command = [sys.executable, CLI, *words, "--character", character]
    done = subprocess.run(command, capture_output=True, text=True)
    raw = done.stdout.strip() or done.stderr.strip()
    try:
        return json.loads(raw or "{}")
    except ValueError:
        raise Stop("cli_unreadable", raw[:400] or "no output")


def read_state(character: str) -> dict:
    result = cli(character, "state", "--full")
    state = result.get("state")
    if not isinstance(state, dict):
        raise Stop("no_state", json.dumps(result)[:400])
    return state


def act(character: str, kind: str, fields: dict) -> dict:
    return cli(character, "act", kind, "--json", json.dumps(fields))


def skill_of(state: dict, name: str) -> dict:
    for row in state.get("skills") or []:
        if str(row.get("name", "")).lower() == name.lower():
            base = row.get("baseLevel")
            return {
                "level": base if isinstance(base, int) else row.get("level"),
                "experience": row.get("experience") or 0,
            }
    raise Stop("unknown_skill", name)


def pick_target(state: dict, args) -> tuple:
    """The nearest reachable target whose own menu offers the wanted option.

    The option index is read off the target every round rather than
    remembered: menus are built per target, and a valid index pointing at the
    wrong entry dispatches happily and trains nothing.
    """
    wanted = args.option.lower()
    if args.npc:
        rows, kind, name = state.get("nearbyNpcs") or [], "npc", args.npc.lower()
    else:
        rows, kind, name = state.get("nearbyLocs") or [], "loc", args.loc.lower()
    found = []
    for row in rows:
        if name not in str(row.get("name", "")).lower():
            continue
        if row.get("reachable") is False:
            continue
        for entry in row.get("optionsWithIndex") or []:
            if wanted in str(entry.get("text", "")).lower():
                found.append((row.get("distance", 10**9), row, entry))
                break
    if not found:
        raise Stop(
            "no_target",
            "no reachable %s matching %r offers %r in range"
            % (kind, name, args.option),
        )
    found.sort(key=lambda item: item[0])
    _, row, entry = found[0]
    if kind == "npc":
        fields = {"npcIndex": row.get("index"), "optionIndex": entry.get("opIndex")}
        return "interactNpc", fields, row
    fields = {
        "locId": row.get("id"),
        "x": row.get("x"),
        "z": row.get("z"),
        "optionIndex": entry.get("opIndex"),
    }
    return "interactLoc", fields, row


def clear_continuation(character: str, state: dict) -> bool:
    """Clear a dialog that only continues, or stop on one that asks something.

    A level-up page is the common case: it opens on its own mid-grind and
    freezes combat and experience until something clicks it away. A dialog
    with real choices is a decision, so the loop hands it back instead.
    """
    dialog = state.get("dialog") or {}
    if not dialog.get("isOpen"):
        return False
    options = dialog.get("options") or []
    if options:
        raise Stop("dialog_choice", json.dumps(options)[:400])
    act(character, "clickDialogOption", {"optionIndex": 0})
    return True


def guard(state: dict, args) -> None:
    player = state.get("player") or {}
    if player.get("isDead"):
        raise Stop("died", "inventory is lost on death; re-equip before resuming")
    hp = player.get("hp")
    if isinstance(hp, int) and hp <= args.min_hp:
        raise Stop("low_hp", "hp %d at or under --min-hp %d" % (hp, args.min_hp))
    inventory = state.get("inventory") or []
    if args.stop_when_full and len(inventory) >= 28:
        raise Stop("inventory_full", "28 slots used; bank or drop before resuming")


def emit(row: dict) -> None:
    print(json.dumps(row, separators=(",", ":")), flush=True)


def train(args) -> str:
    character = args.character
    state = read_state(character)
    skill = skill_of(state, args.skill)
    emit({"start": args.skill, **skill, "target": args.target_level})
    stale = 0
    for round_number in range(1, args.max_rounds + 1):
        guard(state, args)
        if clear_continuation(character, state):
            state = read_state(character)
        skill = skill_of(state, args.skill)
        if args.target_level and skill["level"] >= args.target_level:
            return "target_reached"
        kind, fields, row = pick_target(state, args)
        result = act(character, kind, fields)
        # The CLI echoes the label its optionIndex matched. A mismatch here is
        # the silent failure this whole loop exists to avoid.
        option = result.get("option")
        if option is not None and args.option.lower() not in str(option).lower():
            raise Stop("wrong_option", "optionIndex selected %r" % option)
        waited = cli(character, "wait", str(args.ticks))
        state = read_state(character)
        after = skill_of(state, args.skill)
        gained = after["experience"] - skill["experience"]
        emit(
            {
                "round": round_number,
                "tick": state.get("tick"),
                "target": row.get("name"),
                "option": option,
                "dispatched": bool(result.get("success")),
                "reason": result.get("reason"),
                "level": after["level"],
                "experience": after["experience"],
                "gained": gained,
                "hp": (state.get("player") or {}).get("hp"),
                "waited": bool(waited.get("success", True)),
            }
        )
        stale = 0 if gained > 0 else stale + 1
        if stale >= args.patience:
            raise Stop(
                "no_progress",
                "no experience in %d rounds; check adjacency, the option label, "
                "and whether the target is fightable at all" % stale,
            )
    return "max_rounds"


def parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repeat one interaction until a skill reaches a level."
    )
    parser.add_argument("--character", required=True)
    parser.add_argument("--skill", required=True, help="Skill to watch, e.g. Attack")
    parser.add_argument("--target-level", type=int, default=0, help="0 runs the rounds")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--npc", help="Substring of the NPC's name")
    target.add_argument("--loc", help="Substring of the location's name")
    parser.add_argument(
        "--option", required=True, help='Menu entry to use, e.g. Attack or "Chop down"'
    )
    parser.add_argument("--ticks", type=int, default=6, help="Ticks per round (1-100)")
    parser.add_argument("--max-rounds", type=int, default=40)
    parser.add_argument(
        "--patience", type=int, default=5, help="Rounds without experience to allow"
    )
    parser.add_argument("--min-hp", type=int, default=5, help="Stop at or under this")
    parser.add_argument(
        "--stop-when-full",
        action="store_true",
        help="Stop once all 28 inventory slots are used (gathering skills)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.ticks <= 100:
        parser.error("--ticks must be 1-100")
    return args


def main(argv) -> int:
    args = parse(argv)
    try:
        outcome = train(args)
    except Stop as stop:
        emit({"done": stop.reason, "detail": stop.detail})
        return 2
    except KeyboardInterrupt:
        emit({"done": "interrupted", "detail": "the character keeps its last action"})
        return 2
    emit({"done": outcome})
    return 0 if outcome == "target_reached" else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
