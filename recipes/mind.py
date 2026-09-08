#!/usr/bin/env python3
"""Run a character from goals and rules instead of an ordered list of steps.

A plan that is a list of recipe calls can only be right about one situation.
It fixes, at the time it is written, what to do -- so the character carries on
attacking after its runes ran out, walks to a shop that was never found, or
retries the fight that just nearly killed it, because the list says that step
comes next. Every workaround for that (a fallback list, a cooldown for one
specific stop reason, a linter that checks two plans agree where the meeting
point is) is a patch over the same missing idea: the decision depends on the
situation, and the situation is not in the plan.

This is the situation, made available to the decision. It borrows the shape
from GOAL, an agent language built on the same three parts:

- **Beliefs.** One reading of the world, one set of names for it. Every raw
  state key the fleet cares about is written down in `Beliefs` and nowhere
  else, so a key that changes name in the world fails loudly here instead of
  quietly returning nothing to nine separate readers.
- **Goals.** Stated as a condition on those beliefs, not as a count kept by
  the recipe doing the work. A goal is dropped the moment it is believed
  achieved, so nothing has to be told it is finished.
- **Rules.** Ordered `when` -> `then`. The first rule whose condition holds
  runs its recipe. The order is the character's priority; the conditions are
  what makes it a decision rather than a sequence.

The fourth part is not GOAL's, and is the reason this earns its place here:
**every stop reason becomes a fact**. A recipe that stops `low_hp` or
`out_of_runes` writes that, with a timestamp, to `memory.jsonl`, and the next
cycle can ask about it -- `not failed_recently('train', 'low_hp', 900)`. Stop
reasons used to end up as prose in LEARNINGS.md that only a human ever read,
which is how a character kept re-entering the fight that killed it. Nothing
here special-cases a reason; a cooldown is an ordinary condition, and so is
"we already looked for a shop here and there wasn't one".

    uv run recipes/mind.py --character gorruk --mind recipes/minds/example.json
    uv run recipes/mind.py --character gorruk --mind recipes/minds/gorruk.json --loop

A mind file:

    {
      "goals": [
        {"name": "attack_20", "satisfied": "level('Attack') >= 20"}
      ],
      "rules": [
        {
          "name": "retreat_when_the_last_fight_went_badly",
          "when": "failed_recently('train', 'low_hp', 900)",
          "then": {"recipe": "travel", "argv": ["--x", "3222", "--z", "3218"]}
        },
        {
          "name": "otherwise_train",
          "when": "",
          "then": {"recipe": "train", "argv": ["--npc", "goblin", "..."]}
        }
      ]
    }

`when` is a Python expression over the beliefs below; an empty one always
matches, so put it last as the catch-all. `then` names a recipe beside this
file and the flags to pass it, minus `--character`, which this adds. A `note`
on any goal or rule is ignored by the runtime and kept for whoever reads the
file next.

Goals are conditions, re-checked every cycle, not entries in a list that get
crossed off: a goal whose condition stops holding (runes spent, a level
drained) comes back on its own. When every goal holds, the run is over. A
mind with no goals at all is never over: that is a character that reacts for
as long as it is left running, stopped by `--stop-file`, `--max-cycles` or a
situation its rules have no answer to.

What a `when` may ask, and nothing else:

    hp  max_hp  hp_ratio  dead  x  z  run_energy
    carrying  free_slots  inventory_full  goals
    level(skill)              trained level, e.g. level('Magic')
    xp(skill)                 experience
    have(item)                count in inventory, by id or name substring
    at(x, z, radius=3)        standing within radius of a tile
    npc_near(name, within=15)     count of matching reachable NPCs
    loc_near(name, within=15)     ... locations
    player_near(name, within=15)  ... other players
    ground_near(item, within=6)   ... items on the floor
    dialog_open()             a dialog is waiting
    known(landmark)           routes.json has confirmed this landmark
    goal(name)                that goal is still open this cycle
    failed_recently(recipe=None, reason=None, seconds=600)
    succeeded_recently(recipe=None, reason=None, seconds=600)
    since(recipe=None, reason=None)   seconds since that outcome, else inf

Output is one JSON object per line: a `cycle` line naming the open goals and
any just achieved, a `chose` line naming the matched rule, then that recipe's
own lines forwarded verbatim as they arrive, then a final `done` line. Exit
status is 0 when every goal was achieved (or `--stop-file` appeared), 2 when
it stopped for a reason the owner should look at (`no_rule_matched`,
`stalled`, `died`, `max_cycles`), and 1 for a broken mind file, a broken
expression, or a world that no longer answers in the shape `Beliefs` reads.
Without `--loop` it runs one cycle and exits with the recipe's own status,
so a single decision can be dropped into a shell the same way a recipe can.

`when` expressions are evaluated with `eval` against the names above and no
builtins beyond a handful of safe ones. That is a real `eval`, on a file the
owner or the agent wrote and nobody else can reach; it is not a sandbox, and
a mind file deserves the same trust as a recipe. It buys the one thing a
JSON condition tree cannot: an owner or an agent writes
`have(558) >= 1 and hp_ratio > 0.4` correctly the first time, and the set of
askable questions never has to grow a new keyword to express an `and`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.normpath(os.path.join(HERE, "..", "clawscape.py"))
DEFAULT_MEMORY = os.path.join(HERE, "memory.jsonl")
DEFAULT_ROUTES = os.path.join(HERE, "routes.json")

# A recipe is a plain name resolved beside this file -- never a path, so a
# mind file cannot name an executable outside the recipe set.
RECIPE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
INVENTORY_SLOTS = 28
FOREVER = float("inf")

# Sections that must be present for a cycle to mean anything at all. The rest
# are checked where they are used, so an absent one is an error at the moment
# a rule asks about it rather than a silent zero forever after.
REQUIRED_SECTIONS = ("player", "skills", "inventory")

SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "float": float,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "sorted": sorted,
    "str": str,
    "sum": sum,
}

# A broken mind file, a broken expression or a world that answers in a shape
# the beliefs cannot read are all things a retry cannot fix; they exit 1 so a
# harness can tell them apart from a character that merely stopped.
BROKEN = {
    "bad_mind",
    "bad_expression",
    "unknown_recipe",
    "state_schema",
    "no_state",
    "cli_unreadable",
}


class Stop(Exception):
    """The run is over; `reason` says why, in one machine-readable word."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def emit(row: dict) -> None:
    print(json.dumps(row, sort_keys=True), flush=True)


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


class Beliefs:
    """One reading of the world, under the only names a rule may use.

    Every raw key from `state --full` that anything here reads appears in this
    class and in no other file. A section that has gone missing raises
    `state_schema` naming the key, which is the whole point: a reader that
    reaches for a renamed key with `.get()` gets an empty list back and keeps
    going, reporting nothing wrong while doing nothing at all.
    """

    def __init__(self, state: dict, facts: list, routes: dict, now: float):
        self.state = state
        self.facts = facts
        self.routes = routes
        self.now = now
        for key in REQUIRED_SECTIONS:
            if key not in state:
                raise Stop(
                    "state_schema",
                    "state --full has no %r section; the world's field names "
                    "changed and every belief below it is meaningless" % key,
                )

    def section(self, key: str, empty=None):
        if key not in self.state:
            raise Stop(
                "state_schema",
                "state --full has no %r section; a rule asked about it" % key,
            )
        value = self.state[key]
        return ([] if empty is None else empty) if value is None else value

    @property
    def player(self) -> dict:
        return self.state.get("player") or {}

    def level(self, skill: str) -> int:
        """The trained level, never the live one.

        `baseLevel` is what experience has earned; `level` is drained, boosted,
        or -- for Hitpoints -- current HP rather than a level at all. A goal
        watching the wrong one is achieved by eating a fish.
        """
        row = self._skill(skill)
        base = row.get("baseLevel")
        return base if isinstance(base, int) else (row.get("level") or 0)

    def xp(self, skill: str) -> int:
        return self._skill(skill).get("experience") or 0

    def _skill(self, skill: str) -> dict:
        for row in self.section("skills"):
            if str(row.get("name", "")).lower() == str(skill).lower():
                return row
        raise Stop("bad_expression", "no skill named %r" % skill)

    def have(self, item) -> int:
        """How many of an item are carried, by id or by name substring."""
        total = 0
        for row in self.section("inventory"):
            if self._matches(row, item):
                total += row.get("count") or 1
        return total

    def at(self, x: int, z: int, radius: int = 3) -> bool:
        here_x, here_z = self.player.get("worldX"), self.player.get("worldZ")
        if here_x is None or here_z is None:
            return False
        return abs(here_x - x) <= radius and abs(here_z - z) <= radius

    def npc_near(self, name, within: int = 15) -> int:
        return self._near("nearbyNpcs", name, within)

    def loc_near(self, name, within: int = 15) -> int:
        return self._near("nearbyLocs", name, within)

    def player_near(self, name, within: int = 15) -> int:
        return self._near("nearbyPlayers", name, within)

    def ground_near(self, item, within: int = 6) -> int:
        return self._near("groundItems", item, within)

    def dialog_open(self) -> bool:
        return bool((self.section("dialog", {}) or {}).get("isOpen"))

    def known(self, landmark: str) -> bool:
        return str(landmark) in (self.routes.get("landmarks") or {})

    def since(self, recipe=None, reason=None) -> float:
        """Seconds since the most recent matching outcome, or inf if never."""
        best = FOREVER
        for row in self.facts:
            if recipe is not None and row.get("recipe") != recipe:
                continue
            if reason is not None and row.get("reason") != reason:
                continue
            elapsed = self.now - (row.get("t") or 0)
            if 0 <= elapsed < best:
                best = elapsed
        return best

    def failed_recently(self, recipe=None, reason=None, seconds: float = 600) -> bool:
        return self._since_where(False, recipe, reason) < seconds

    def succeeded_recently(self, recipe=None, reason=None, seconds: float = 600):
        return self._since_where(True, recipe, reason) < seconds

    def _since_where(self, ok: bool, recipe, reason) -> float:
        best = FOREVER
        for row in self.facts:
            if bool(row.get("ok")) != ok:
                continue
            if recipe is not None and row.get("recipe") != recipe:
                continue
            if reason is not None and row.get("reason") != reason:
                continue
            elapsed = self.now - (row.get("t") or 0)
            if 0 <= elapsed < best:
                best = elapsed
        return best

    def _near(self, key: str, name, within: int) -> int:
        found = 0
        for row in self.section(key):
            if not self._matches(row, name):
                continue
            if row.get("reachable") is False:
                continue
            distance = row.get("distance")
            if isinstance(distance, int) and distance > within:
                continue
            found += 1
        return found

    @staticmethod
    def _matches(row: dict, wanted) -> bool:
        if isinstance(wanted, int):
            return row.get("id") == wanted
        return str(wanted).lower() in str(row.get("name", "")).lower()

    def namespace(self) -> dict:
        """The names a `when` or `satisfied` expression may use.

        Plain values come from the required sections, so they are read once
        here. Everything that touches an optional section is a function, so
        the section is only demanded of the world when a rule actually asks.
        """
        player = self.player
        hp = player.get("hp") or 0
        max_hp = player.get("maxHp") or 0
        carrying = len(self.section("inventory"))
        return {
            "hp": hp,
            "max_hp": max_hp,
            "hp_ratio": (hp / max_hp) if max_hp else 0.0,
            "dead": bool(player.get("isDead")),
            "x": player.get("worldX"),
            "z": player.get("worldZ"),
            "run_energy": player.get("runEnergy") or 0,
            "carrying": carrying,
            "free_slots": max(0, INVENTORY_SLOTS - carrying),
            "inventory_full": carrying >= INVENTORY_SLOTS,
            "level": self.level,
            "xp": self.xp,
            "have": self.have,
            "at": self.at,
            "npc_near": self.npc_near,
            "loc_near": self.loc_near,
            "player_near": self.player_near,
            "ground_near": self.ground_near,
            "dialog_open": self.dialog_open,
            "known": self.known,
            "since": self.since,
            "failed_recently": self.failed_recently,
            "succeeded_recently": self.succeeded_recently,
        }


def evaluate(expression: str, namespace: dict, where: str) -> bool:
    try:
        return bool(eval(expression, {"__builtins__": SAFE_BUILTINS}, namespace))
    except Stop:
        raise
    except Exception as error:
        raise Stop(
            "bad_expression",
            "%s: %s: %s" % (where, type(error).__name__, error),
        )


def load_mind(path: str) -> dict:
    """Read a mind file and refuse the shapes that would fail later, quietly.

    A mind file is checked every cycle rather than once at startup, because
    the point of keeping goals and rules in a file is that they can be
    rewritten while the character is still working.
    """
    try:
        with open(path) as handle:
            mind = json.load(handle)
    except (OSError, ValueError) as error:
        raise Stop("bad_mind", "%s: %s" % (path, error))
    if not isinstance(mind, dict):
        raise Stop("bad_mind", "a mind file is an object with goals and rules")

    goals = mind.get("goals") or []
    rules = mind.get("rules") or []
    if not isinstance(goals, list) or not isinstance(rules, list):
        raise Stop("bad_mind", "goals and rules are both lists")
    if not rules:
        raise Stop("bad_mind", "no rules; a mind with no rules can do nothing")

    seen = set()
    for index, goal in enumerate(goals):
        where = "goal %d" % index
        if not isinstance(goal, dict):
            raise Stop("bad_mind", "%s is not an object" % where)
        name = goal.get("name")
        if not name or not isinstance(name, str):
            raise Stop("bad_mind", "%s has no name" % where)
        if not goal.get("satisfied"):
            raise Stop(
                "bad_mind",
                "goal %r has no `satisfied` condition, so nothing could ever "
                "drop it" % name,
            )
        if name in seen:
            raise Stop("bad_mind", "two goals named %r" % name)
        seen.add(name)

    seen = set()
    for index, rule in enumerate(rules):
        where = "rule %d" % index
        if not isinstance(rule, dict):
            raise Stop("bad_mind", "%s is not an object" % where)
        name = rule.get("name")
        if not name or not isinstance(name, str):
            raise Stop("bad_mind", "%s has no name" % where)
        if name in seen:
            raise Stop("bad_mind", "two rules named %r" % name)
        seen.add(name)
        if "when" not in rule:
            raise Stop(
                "bad_mind",
                'rule %r has no `when`; write "" for a catch-all, so that a '
                "rule matching everything is something someone chose" % name,
            )
        check_call(rule.get("then"), "rule %r" % name)
    return {"goals": goals, "rules": rules}


def check_call(call, where: str) -> None:
    if not isinstance(call, dict):
        raise Stop("bad_mind", "%s has no `then` recipe call" % where)
    name = call.get("recipe")
    if not isinstance(name, str) or not RECIPE_NAME.match(name):
        raise Stop("bad_mind", "%s names no recipe (got %r)" % (where, name))
    if not os.path.exists(os.path.join(HERE, name + ".py")):
        raise Stop("unknown_recipe", "%s: no recipes/%s.py" % (where, name))
    argv = call.get("argv") or []
    if not isinstance(argv, list) or any(
        not isinstance(word, (str, int, float)) for word in argv
    ):
        raise Stop("bad_mind", "%s: argv is a list of flags and values" % where)
    if "--character" in [str(word) for word in argv]:
        raise Stop(
            "bad_mind",
            "%s: leave --character out of argv; the mind passes its own, and a "
            "second one silently drives someone else's character" % where,
        )


def load_facts(path: str, character: str) -> list:
    """Past outcomes for this character, as facts a rule can ask about."""
    facts = []
    if not os.path.exists(path):
        return facts
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("character") == character:
                facts.append(row)
    return facts


def record_fact(path: str, row: dict) -> None:
    """Append one outcome. One short line, opened for append, so several
    characters writing at once interleave lines rather than losing them."""
    with open(path, "a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def load_routes(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def open_goals(goals: list, namespace: dict) -> tuple:
    """Split the goals into the ones still to do and the ones now believed."""
    still_open, achieved = [], []
    for goal in goals:
        where = "goal %r" % goal["name"]
        if evaluate(goal["satisfied"], namespace, where):
            achieved.append(goal["name"])
        else:
            still_open.append(goal["name"])
    return still_open, achieved


def select(rules: list, namespace: dict, explain: bool):
    """The first rule whose condition holds, and why the others did not."""
    considered = []
    for rule in rules:
        when = (rule.get("when") or "").strip()
        matched = True
        if when:
            matched = evaluate(when, namespace, "rule %r" % rule["name"])
        if explain:
            considered.append({"rule": rule["name"], "matched": bool(matched)})
        if matched:
            return rule, considered
    return None, considered


def run_recipe(character: str, call: dict) -> tuple:
    """Run one recipe, forwarding its lines as they arrive.

    Recipes stay separate processes: a recipe that crashes takes down its own
    round and nothing else, and its output is already one JSON object per
    line, so forwarding it keeps the whole run readable as a single log.
    """
    path = os.path.join(HERE, call["recipe"] + ".py")
    argv = [str(word) for word in call.get("argv") or []]
    command = [sys.executable, path, *argv, "--character", character]
    # stderr goes to a file rather than a second pipe. Draining one pipe to
    # the end while the other fills its buffer is a deadlock: the child blocks
    # writing the traceback nobody is reading yet, and the parent blocks
    # waiting for the stdout line that will never come. A --loop run failing
    # that way hangs silently, which is the worst shape a stop can take here.
    last = {}
    with tempfile.TemporaryFile("w+") as errors:
        # The `with` matters: it closes the stdout pipe. A --loop run leaks one
        # file descriptor per cycle without it, and only finds out hours later.
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=errors, text=True
        ) as process:
            for line in process.stdout:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                print(line, flush=True)
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and "done" in row:
                    last = row
            code = process.wait()
        errors.seek(0)
        stderr = errors.read().strip()
    reason = last.get("done")
    if not reason:
        # A recipe that dies without a `done` line has still told us
        # something; keep it rather than reporting an outcome of None.
        reason = "no_outcome"
    return reason, last.get("detail") or stderr[:400], code


def cycle(args, mind: dict, facts: list, routes: dict) -> tuple:
    """One observe, drop, decide, act. Returns (outcome, detail, exit code)."""
    state = read_state(args.character)
    beliefs = Beliefs(state, facts, routes, time.time())
    namespace = beliefs.namespace()
    if namespace["dead"]:
        raise Stop("died", "everything after this assumes a live, equipped character")

    still_open, achieved = open_goals(mind["goals"], namespace)
    emit(
        {
            "cycle": args.cycle,
            "character": args.character,
            "goals": still_open,
            "achieved": achieved,
            "hp": namespace["hp"],
            "at": [namespace["x"], namespace["z"]],
        }
    )
    if mind["goals"] and not still_open:
        return "goals_achieved", "", 0

    namespace["goals"] = list(still_open)
    namespace["goal"] = lambda name: name in still_open

    rule, considered = select(mind["rules"], namespace, args.explain)
    if args.explain:
        emit({"considered": considered})
    if rule is None:
        raise Stop(
            "no_rule_matched",
            "no rule fits the situation and none is a catch-all; the mind file "
            "has a gap worth naming rather than a default worth hiding",
        )
    emit({"chose": rule["name"], "recipe": rule["then"]["recipe"]})
    if args.dry_run:
        return "dry_run", rule["name"], 0

    reason, detail, code = run_recipe(args.character, rule["then"])
    record_fact(
        args.memory,
        {
            "t": time.time(),
            "character": args.character,
            "rule": rule["name"],
            "recipe": rule["then"]["recipe"],
            "reason": reason,
            "detail": detail[:400],
            "ok": code == 0,
        },
    )
    if reason == "died":
        raise Stop("died", "a step reported death; later rules assume otherwise")
    return reason, detail, code


def run(args) -> tuple:
    repeated = 0
    previous = None
    while True:
        args.cycle += 1
        if args.stop_file and os.path.exists(args.stop_file):
            return "stop_file", args.stop_file, 0

        mind = load_mind(args.mind)
        facts = load_facts(args.memory, args.character)
        routes = load_routes(args.routes)
        outcome, detail, code = cycle(args, mind, facts, routes)

        if outcome in ("goals_achieved", "dry_run"):
            return outcome, detail, 0
        if not args.loop:
            return outcome, detail, code

        # The same rule stopping the same way over and over is the shape of a
        # character busy doing nothing: each round looks ordinary on its own,
        # and only the repetition says the situation will not resolve itself.
        signature = (outcome, detail[:80])
        repeated = repeated + 1 if signature == previous else 0
        previous = signature
        if repeated + 1 >= args.patience:
            raise Stop(
                "stalled",
                "%d cycles ending %s; the rules have no answer to this "
                "situation" % (repeated + 1, outcome),
            )
        if args.max_cycles and args.cycle >= args.max_cycles:
            return "max_cycles", "", 2


def parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a character from goals and rules, not a list of steps."
    )
    parser.add_argument("--character", required=True)
    parser.add_argument("--mind", required=True, help="Path to a mind file")
    parser.add_argument("--loop", action="store_true", help="Keep going after a step")
    parser.add_argument("--max-cycles", type=int, default=0, help="0 is unlimited")
    parser.add_argument(
        "--patience",
        type=int,
        default=4,
        help="Identical outcomes in a row to call a run stalled",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Choose a rule, run nothing"
    )
    parser.add_argument(
        "--explain", action="store_true", help="Report every rule considered"
    )
    parser.add_argument("--stop-file", help="Stop gracefully once this path exists")
    parser.add_argument("--memory", default=DEFAULT_MEMORY)
    parser.add_argument("--routes", default=DEFAULT_ROUTES)
    args = parser.parse_args(argv)
    if args.patience < 2:
        parser.error("--patience must be 2 or more")
    args.cycle = 0
    return args


def main(argv) -> int:
    args = parse(argv)
    try:
        outcome, detail, code = run(args)
    except Stop as stop:
        emit({"done": stop.reason, "detail": stop.detail})
        return 1 if stop.reason in BROKEN else 2
    except KeyboardInterrupt:
        emit({"done": "interrupted", "detail": "the character keeps its last action"})
        return 2
    emit({"done": outcome, "detail": detail})
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
