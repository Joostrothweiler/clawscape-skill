"""Offline checks: nothing here reaches a world."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = load("clawscape", "clawscape.py")


def run(*words: str):
    done = subprocess.run(
        [sys.executable, os.path.join(ROOT, "clawscape.py"), *words],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAWSCAPE_HOME": os.path.join(ROOT, ".test-home")},
    )
    # A failure is reported as JSON on stderr, like every other result.
    return done.returncode, (done.stdout.strip() or done.stderr.strip())


class Commands(unittest.TestCase):
    def test_help_lists_the_commands_an_agent_needs(self):
        code, out = run("help")
        self.assertEqual(code, 0)
        for command in (
            "connect",
            "state",
            "act ",
            "wait ",
            "forum list",
            "hiscores",
            "looks",
        ):
            self.assertIn(command, out)

    def test_actions_lists_every_type_and_one_type_s_fields(self):
        code, out = run("actions")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(json.loads(out)["actions"]), sorted(cli.ACTION_FIELDS))
        code, out = run("actions", "interactNpc")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["required"], ["npcIndex", "optionIndex"])

    def test_an_unknown_field_names_the_field_it_meant(self):
        code, out = run("act", "interactNpc", "--json", '{"index":1,"npcIndex":2}')
        self.assertEqual(code, 1)
        self.assertIn("optionIndex, not index", json.loads(out)["error"])

    def test_a_missing_field_is_refused_before_the_call(self):
        code, out = run("act", "interactNpc", "--json", '{"npcIndex":2}')
        self.assertEqual(code, 1)
        self.assertIn("optionIndex", json.loads(out)["error"])


class SkillRows(unittest.TestCase):
    """The trained level is what a caller training a skill watches."""

    def test_hitpoints_reports_its_level_not_its_current_hp(self):
        row = cli.skill_row(
            {"name": "Hitpoints", "level": 7, "baseLevel": 11, "experience": 1358}
        )
        self.assertEqual(row["level"], 11)
        self.assertEqual(row["current"], 7)

    def test_an_unboosted_skill_carries_no_current(self):
        row = cli.skill_row(
            {"name": "Attack", "level": 16, "baseLevel": 16, "experience": 3973}
        )
        self.assertNotIn("current", row)

    def test_a_world_without_baselevel_still_reports_a_level(self):
        row = cli.skill_row({"name": "Woodcutting", "level": 5, "experience": 400})
        self.assertEqual(row["level"], 5)
        self.assertNotIn("current", row)


class OptionLabels(unittest.TestCase):
    """A valid index aimed at the wrong entry is the silent failure."""

    npcs = {
        "nearbyNpcs": [
            {
                "index": 3,
                "name": "Goblin",
                "optionsWithIndex": [
                    {"text": "Attack", "opIndex": 2},
                    {"text": "Examine", "opIndex": 3},
                ],
            }
        ]
    }

    def test_the_matched_label_comes_back(self):
        note = cli.option_note(
            self.npcs, {"type": "interactNpc", "npcIndex": 3, "optionIndex": 2}
        )
        self.assertEqual(note, {"option": "Attack"})

    def test_an_index_matching_nothing_reports_the_real_options(self):
        note = cli.option_note(
            self.npcs, {"type": "interactNpc", "npcIndex": 3, "optionIndex": 1}
        )
        self.assertIsNone(note["option"])
        self.assertEqual(note["options"], {2: "Attack", 3: "Examine"})

    def test_a_target_that_is_not_in_the_snapshot_says_nothing(self):
        note = cli.option_note(
            self.npcs, {"type": "interactNpc", "npcIndex": 9, "optionIndex": 2}
        )
        self.assertEqual(note, {})

    def test_dialog_zero_is_continue_and_choices_count_from_one(self):
        dialog = {"dialog": {"options": [{"index": 1, "text": "Yes"}]}}
        self.assertEqual(
            cli.option_note(dialog, {"type": "clickDialogOption", "optionIndex": 0}),
            {"option": "continue"},
        )
        self.assertEqual(
            cli.option_note(dialog, {"type": "clickDialogOption", "optionIndex": 1}),
            {"option": "Yes"},
        )

    def test_players_carry_no_option_list_so_nothing_is_invented(self):
        state = {"nearbyPlayers": [{"index": 7, "name": "arete"}]}
        note = cli.option_note(
            state, {"type": "interactPlayer", "playerIndex": 7, "optionIndex": 4}
        )
        self.assertEqual(note, {})


class Looks(unittest.TestCase):
    """The restyle command builds the request; the world does the deciding."""

    def test_only_what_is_named_is_sent(self):
        args = cli.Arguments(
            [
                "set",
                "--character",
                "miner",
                "--hair",
                "man_hair_long",
                "--legs",
                "36",
                "--skin",
                "3",
                "--torso-colour",
                "6",
            ]
        )
        args.shift()
        wanted = {"character": "miner"}
        parts = {}
        for part in ("hair", "jaw", "torso", "arms", "hands", "legs", "feet"):
            if part in args.options:
                choice = args.options[part]
                parts[part] = int(choice) if choice.isdigit() else choice
        # A kit is a name or an id; a colour is always an index.
        self.assertEqual(parts, {"hair": "man_hair_long", "legs": 36})
        self.assertEqual(cli.whole_number("3", "skin"), 3)
        with self.assertRaises(cli.Failure):
            cli.whole_number("dark", "skin")
        self.assertEqual(list(wanted), ["character"])

    def test_a_restyle_that_names_nothing_is_refused_before_the_call(self):
        code, out = run("looks", "set", "--character", "miner")
        self.assertEqual(code, 1)
        self.assertIn("Name what to change", json.loads(out)["error"])

    def test_an_unknown_subcommand_says_what_there_is(self):
        code, out = run("looks", "wear", "--character", "miner")
        self.assertEqual(code, 1)
        self.assertIn("looks set", json.loads(out)["error"])


class Contract(unittest.TestCase):
    def test_the_cli_and_the_openapi_snapshot_agree_on_the_actions(self):
        with open(os.path.join(ROOT, "openapi.json"), encoding="utf-8") as handle:
            document = json.load(handle)
        action = document["components"]["schemas"]["Action"]
        self.assertEqual(
            sorted(action["properties"]["type"]["enum"]), sorted(cli.ACTION_FIELDS)
        )
        for kind, fields in action["x-action-fields"].items():
            shape = cli.ACTION_FIELDS[kind]
            expected = shape["required"] + ["%s?" % name for name in shape["optional"]]
            self.assertEqual(fields, expected, kind)

    def test_every_documented_action_appears_in_the_reference(self):
        with open(os.path.join(ROOT, "references/actions.md"), encoding="utf-8") as f:
            reference = f.read()
        for kind in cli.ACTION_FIELDS:
            self.assertIn(kind, reference, kind)


class Recipes(unittest.TestCase):
    def test_train_refuses_a_tick_count_the_world_will_not_accept(self):
        done = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "recipes/train.py"),
                "--character",
                "demo",
                "--skill",
                "Attack",
                "--npc",
                "goblin",
                "--option",
                "Attack",
                "--ticks",
                "500",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 2)
        self.assertIn("--ticks must be 1-100", done.stderr)

    def test_train_needs_exactly_one_kind_of_target(self):
        done = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "recipes/train.py"),
                "--character",
                "demo",
                "--skill",
                "Attack",
                "--npc",
                "goblin",
                "--loc",
                "tree",
                "--option",
                "Attack",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 2)
        self.assertIn("not allowed with argument", done.stderr)

    def test_a_dialog_with_real_choices_is_handed_back(self):
        train = load("train", "recipes/train.py")
        with self.assertRaises(train.Stop) as caught:
            train.clear_continuation(
                "demo", {"dialog": {"isOpen": True, "options": [{"index": 1}]}}
            )
        self.assertEqual(caught.exception.reason, "dialog_choice")

    def test_a_closed_dialog_needs_no_clearing(self):
        train = load("train", "recipes/train.py")
        self.assertFalse(
            train.clear_continuation("demo", {"dialog": {"isOpen": False}})
        )

    def test_the_nearest_target_offering_the_option_wins(self):
        train = load("train", "recipes/train.py")
        args = train.parse(
            [
                "--character",
                "demo",
                "--skill",
                "Woodcutting",
                "--loc",
                "tree",
                "--option",
                "Chop down",
            ]
        )
        state = {
            "nearbyLocs": [
                {
                    "id": 1,
                    "name": "Tree",
                    "x": 5,
                    "z": 5,
                    "distance": 9,
                    "optionsWithIndex": [{"text": "Chop down", "opIndex": 1}],
                },
                {
                    "id": 2,
                    "name": "Tree",
                    "x": 6,
                    "z": 6,
                    "distance": 2,
                    "optionsWithIndex": [{"text": "Chop down", "opIndex": 3}],
                },
                {
                    "id": 3,
                    "name": "Tree stump",
                    "x": 7,
                    "z": 7,
                    "distance": 1,
                    "optionsWithIndex": [{"text": "Examine", "opIndex": 1}],
                },
            ]
        }
        kind, fields, row = train.pick_target(state, args)
        self.assertEqual(kind, "interactLoc")
        self.assertEqual(fields, {"locId": 2, "x": 6, "z": 6, "optionIndex": 3})
        self.assertEqual(row["name"], "Tree")

    def test_an_unreachable_target_is_not_chosen(self):
        train = load("train", "recipes/train.py")
        args = train.parse(
            [
                "--character",
                "demo",
                "--skill",
                "Attack",
                "--npc",
                "goblin",
                "--option",
                "Attack",
            ]
        )
        state = {
            "nearbyNpcs": [
                {
                    "index": 1,
                    "name": "Goblin",
                    "distance": 1,
                    "reachable": False,
                    "optionsWithIndex": [{"text": "Attack", "opIndex": 2}],
                }
            ]
        }
        with self.assertRaises(train.Stop) as caught:
            train.pick_target(state, args)
        self.assertEqual(caught.exception.reason, "no_target")


if __name__ == "__main__":
    unittest.main()
