"""Offline checks: nothing here reaches a world."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


class Identity(unittest.TestCase):
    """The charter is the owner's; the journal is the character's own record."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def directory(self) -> str:
        # The digest must be derived the way the subprocess derives it: from a
        # config with no login, not from whatever is in the real ~/.clawscape.
        config = {"server": cli.DEFAULT_SERVER}
        return os.path.join(
            self.home, "identity", cli.identity_digest(config, "gorruk")
        )

    def identity(self, *words: str):
        done = subprocess.run(
            [sys.executable, os.path.join(ROOT, "clawscape.py"), "identity", *words],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAWSCAPE_HOME": self.home,
                "CLAWSCAPE_CHARACTER": "gorruk",
            },
        )
        raw = done.stdout.strip() or done.stderr.strip()
        return done.returncode, json.loads(raw) if raw else {}

    def test_a_resolved_commitment_leaves_the_record_however_old_it_is(self):
        rows = [
            {"kind": "commitment", "at": "2026-08-01T10:00:00Z", "id": "c7"},
            {"kind": "commitment", "at": "2026-09-01T10:00:00Z", "id": "c9"},
            {
                "kind": "commitment",
                "at": "2026-09-02T10:00:00Z",
                "id": "c7",
                "state": "closed",
            },
        ]
        view = cli.project_standing(rows)
        self.assertEqual([row["id"] for row in view["commitments"]], ["c9"])

    def test_a_relation_keeps_only_its_latest_line_per_name(self):
        rows = [
            {
                "kind": "relation",
                "at": "2026-09-01T10:00:00Z",
                "who": "thrag",
                "text": "traded fairly",
            },
            {
                "kind": "relation",
                "at": "2026-09-02T10:00:00Z",
                "who": "thrag",
                "text": "scammed me",
            },
            {
                "kind": "relation",
                "at": "2026-09-02T11:00:00Z",
                "who": "mira",
                "text": "ally",
            },
        ]
        view = cli.project_standing(rows)
        self.assertEqual(view["counts"]["relations"], 2)
        self.assertEqual(
            {row["who"]: row["text"] for row in view["relations"]},
            {"thrag": "scammed me", "mira": "ally"},
        )

    def test_the_capped_buckets_stay_a_bounded_read_and_say_how_many_there_were(self):
        rows = [
            {
                "kind": "milestone",
                "at": "2026-09-%02dT10:00:00Z" % (day + 1),
                "text": "milestone %d" % day,
            }
            for day in range(25)
        ]
        view = cli.project_standing(rows)
        self.assertEqual(len(view["milestones"]), cli.IDENTITY_CAPS["milestones"])
        self.assertEqual(view["counts"]["milestones"], 25)
        # The newest are the ones kept.
        self.assertEqual(view["milestones"][-1]["text"], "milestone 24")

    def test_open_commitments_are_never_trimmed(self):
        rows = [
            {"kind": "commitment", "at": "2026-09-01T10:00:00Z", "id": "c%d" % n}
            for n in range(40)
        ]
        self.assertEqual(len(cli.project_standing(rows)["commitments"]), 40)

    def test_show_names_the_boundary_between_charter_and_journal(self):
        code, answer = self.identity("show")
        self.assertEqual(code, 0)
        self.assertIsNone(answer["charter"])
        self.assertIn("identity charter --body-file", answer["hint"])
        self.assertIn("not instructions", answer["notice"])

    def test_a_note_too_long_to_be_a_summary_is_refused(self):
        code, answer = self.identity("note", "episode", "--text", "x" * 400)
        self.assertEqual(code, 1)
        self.assertIn("not a transcript", answer["error"])

    def test_an_unknown_note_kind_says_what_the_kinds_are(self):
        code, answer = self.identity("note", "feelings", "--text", "hm")
        self.assertEqual(code, 1)
        for kind in cli.IDENTITY_KINDS:
            self.assertIn(kind, answer["error"])

    def test_a_relation_without_a_name_is_refused_before_it_is_written(self):
        code, answer = self.identity("note", "relation", "--text", "nice")
        self.assertEqual(code, 1)
        self.assertIn("--who", answer["error"])

    def test_a_commitment_returns_the_id_that_resolving_it_later_needs(self):
        code, answer = self.identity(
            "note", "commitment", "--who", "thrag", "--text", "owes a willow log"
        )
        self.assertEqual(code, 0)
        code, resolved = self.identity("resolve", answer["id"])
        self.assertEqual((code, resolved), (0, {"resolved": answer["id"]}))
        code, view = self.identity("show")
        self.assertEqual(view["commitments"], [])

    def test_resolving_a_commitment_that_does_not_exist_fails_loudly(self):
        code, answer = self.identity("resolve", "c404")
        self.assertEqual(code, 1)
        self.assertIn("c404", answer["error"])

    def test_closing_a_session_summarizes_it_and_compacts_standing(self):
        self.identity("note", "commitment", "--text", "settle up", "--id", "c1")
        self.identity("note", "episode", "--text", "chopped willows")
        self.identity("resolve", "c1")
        code, answer = self.identity("close", "--summary", "Woodcutting to 34.")
        self.assertEqual(code, 0)
        self.assertTrue(answer["closed"])
        # The resolved commitment and its closing line both leave the file.
        self.assertLess(answer["standing"]["after"], answer["standing"]["before"])
        code, view = self.identity("show")
        self.assertEqual(view["sessions"][-1]["summary"], "Woodcutting to 34.")
        self.assertEqual(view["commitments"], [])

    def test_closing_when_no_session_is_open_says_so(self):
        code, answer = self.identity("close", "--summary", "nothing happened")
        self.assertEqual(code, 1)
        self.assertIn("session opens on connect", answer["error"])

    def test_an_unclosed_session_reads_as_dropped_once_a_later_one_exists(self):
        folder = os.path.join(self.directory(), "sessions")
        os.makedirs(folder)
        for day in ("20260901T100000Z", "20260902T100000Z"):
            with open(os.path.join(folder, day + ".jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"kind": "open", "at": day}) + "\n")
        code, view = self.identity("show")
        self.assertEqual(code, 0)
        self.assertTrue(view["sessions"][0]["dropped"])
        # The newest is still being played, not abandoned.
        self.assertTrue(view["sessions"][1]["open"])
        self.assertNotIn("dropped", view["sessions"][1])

    def test_compaction_folds_only_the_over_cap_sessions_and_keeps_the_raw_lines(self):
        directory = self.directory()
        folder = os.path.join(directory, "sessions")
        os.makedirs(folder)
        for day in range(1, cli.IDENTITY_CAPS["sessions"] + 4):
            stamp = "202608%02dT100000Z" % day
            with open(
                os.path.join(folder, stamp + ".jsonl"), "w", encoding="utf-8"
            ) as f:
                f.write(json.dumps({"kind": "open", "at": stamp}) + "\n")
                f.write(
                    json.dumps(
                        {"kind": "close", "at": stamp, "summary": "day %d" % day}
                    )
                    + "\n"
                )
        code, view = self.identity("show")
        self.assertEqual(len(view["sessions"]), cli.IDENTITY_CAPS["sessions"])
        self.assertEqual(
            view["compaction"]["sessions"], cli.IDENTITY_CAPS["sessions"] + 3
        )
        code, answer = self.identity("compact", "--summary", "August: chopped trees.")
        self.assertEqual((code, answer["compacted"]), (0, 3))
        code, view = self.identity("show")
        self.assertNotIn("compaction", view)
        # An era is one step from a summary written during play, and eras are
        # never folded again.
        self.assertEqual(view["eras"][0]["derived"], 1)
        self.assertEqual(view["eras"][0]["sessions"], 3)
        self.assertEqual(
            sorted(os.listdir(os.path.join(directory, "archive", "sessions"))),
            ["2026080%dT100000Z.jsonl" % day for day in (1, 2, 3)],
        )

    def test_compaction_below_the_cap_changes_nothing(self):
        code, answer = self.identity("compact", "--summary", "nothing to fold")
        self.assertEqual((code, answer["compacted"]), (0, 0))

    def test_a_torn_line_costs_only_itself(self):
        path = os.path.join(self.home, "torn.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"kind":"milestone","at":"2026-09-01T10:00:00Z"}\n')
            handle.write('{"kind":"milestone","at":"2026-0\n')
            handle.write('{"kind":"milestone","at":"2026-09-02T10:00:00Z"}\n')
        self.assertEqual(len(cli.read_lines(path)), 2)

    def test_two_agents_appending_at_once_lose_nothing(self):
        path = os.path.join(self.home, "shared.jsonl")
        done = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import importlib.util,sys\n"
                    "spec=importlib.util.spec_from_file_location('c',%r)\n"
                    "m=importlib.util.module_from_spec(spec)\n"
                    "spec.loader.exec_module(m)\n"
                    "[m.append_line(%r,{'kind':'episode','who':%r,'n':n}) "
                    "for n in range(50)]"
                    % (os.path.join(ROOT, "clawscape.py"), path, who),
                ]
            )
            for who in ("one", "two")
        ]
        for process in done:
            process.wait()
        rows = cli.read_lines(path)
        self.assertEqual(len(rows), 100)
        self.assertEqual(len([row for row in rows if row["who"] == "one"]), 50)


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
