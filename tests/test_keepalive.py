"""The style guard is the one thing here that cannot be allowed to be wrong.

Arete is a pure build. Training Defence is irreversible and ends the
character's purpose, so these tests are about a permanent, silent loss rather
than a bug someone can fix later.
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes"
    ),
)

import keepalive  # noqa: E402

RECIPES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes"
)

# Arete's live scimitar table, copied from a real state read.
SCIMITAR = {
    "currentStyle": 0,
    "styles": [
        {"index": 0, "name": "Chop", "trainsSkills": ["Attack"]},
        {"index": 1, "name": "Slash", "trainsSkills": ["Strength"]},
        {
            "index": 2,
            "name": "Lunge",
            "trainsSkills": ["Attack", "Strength", "Defence"],
        },
        {"index": 3, "name": "Block", "trainsSkills": ["Defence"]},
    ],
}

# A weapon whose index 1 is the Defence style. This is not hypothetical -- it is
# why every hardcoded `--style 1` in this repo's history was a latent bug.
INDEX_ONE_IS_DEFENCE = {
    "currentStyle": 0,
    "styles": [
        {"index": 0, "name": "X", "trainsSkills": ["Attack"]},
        {"index": 1, "name": "Y", "trainsSkills": ["Defence"]},
        {"index": 2, "name": "Z", "trainsSkills": ["Strength"]},
    ],
}


class NeverTrainsAForbiddenSkill(unittest.TestCase):
    def test_picks_the_strength_style_on_a_scimitar(self):
        self.assertEqual(keepalive.choose_style(SCIMITAR, "Strength", ["Defence"]), 1)

    def test_never_picks_an_index_just_because_it_is_one(self):
        """Hardcoding index 1 here would train Defence. Reading picks 2."""
        got = keepalive.choose_style(INDEX_ONE_IS_DEFENCE, "Strength", ["Defence"])
        self.assertEqual(got, 2)
        self.assertNotEqual(got, 1)

    def test_never_returns_a_style_that_trains_a_forbidden_skill(self):
        for table in (SCIMITAR, INDEX_ONE_IS_DEFENCE):
            idx = keepalive.choose_style(table, "Strength", ["Defence"])
            trains = table["styles"][idx]["trainsSkills"]
            self.assertNotIn("Defence", trains)

    def test_mixed_style_is_rejected_even_though_it_trains_the_want(self):
        """Lunge trains Strength AND Defence. Wanting Strength must not excuse it."""
        idx = keepalive.choose_style(SCIMITAR, "Strength", ["Defence"])
        self.assertNotEqual(idx, 2)

    def test_no_safe_style_returns_none_rather_than_guessing(self):
        only_bad = {"styles": [{"index": 0, "trainsSkills": ["Defence"]}]}
        self.assertIsNone(keepalive.choose_style(only_bad, "Strength", ["Defence"]))

    def test_missing_or_empty_data_returns_none(self):
        for table in ({}, None, {"styles": []}, {"styles": [{"index": 0}]}):
            self.assertIsNone(keepalive.choose_style(table, "Strength", ["Defence"]))

    def test_defence_is_forbidden_by_default(self):
        self.assertIn("Defence", keepalive.DEFAULT_FORBID)


if __name__ == "__main__":
    unittest.main()


class HuntRefusesToFightHurt(unittest.TestCase):
    """A character that starts a fight below its heal threshold dies first.

    Measured: sent into level-42 moss giants at 52/94 with Defence 1, dead
    before the loop's first iteration -- the opening log line read hp 0, and it
    then swung at an empty field for 44 rounds because nothing checked whether
    the character was still where it started.
    """

    def setUp(self):
        import hunt

        self.hunt = hunt

    def test_reads_option_index_from_the_npc(self):
        """Option indices are per-NPC, the same trap as combat style indices."""
        npc = {"optionsWithIndex": [{"text": "Attack", "opIndex": 3}]}
        self.assertEqual(self.hunt.option_index(npc, "Attack"), 3)

    def test_unknown_option_falls_back_safely(self):
        self.assertEqual(self.hunt.option_index({}, "Attack"), 1)

    def test_source_guards_health_before_engaging(self):
        src = open(os.path.join(RECIPES_DIR, "hunt.py")).read()
        self.assertIn("too hurt to start", src)

    def test_source_detects_death_by_position(self):
        src = open(os.path.join(RECIPES_DIR, "hunt.py")).read()
        self.assertIn("died and respawned", src)


class TrekMustOpenGates(unittest.TestCase):
    """A closed gate refuses a step exactly like a wall, and says nothing.

    A scout sat at (2936,3450) for 97 legs, 32 detours and 51 replans reporting
    impassable terrain. It was standing ON the road at the Falador/Taverley
    boundary gate -- loc_1596/loc_1597, nameless in loc.pack, the same gate that
    cost a day the first time anyone met it. indoor.py could open gates;
    trek.py could not.
    """

    def test_trek_tries_to_open_blockers(self):
        src = open(os.path.join(RECIPES_DIR, "trek.py")).read()
        self.assertIn("try_open_blocker", src)

    def test_trek_matches_nameless_gate_ids(self):
        src = open(os.path.join(RECIPES_DIR, "trek.py")).read()
        self.assertIn("PASSABLE_IDS", src)

    def test_trek_accepts_pick_lock_not_just_open(self):
        src = open(os.path.join(RECIPES_DIR, "trek.py")).read()
        self.assertIn("pick lock", src)


class SupervisorKeepsWorkRunning(unittest.TestCase):
    """keepalive keeps a character connected; nothing kept it busy.

    Those failures look identical from outside -- a character standing still,
    online, healthy, achieving nothing -- and on 2026-09-14 three characters sat
    idle at once until Mike said "it seems like you're stuck".
    """

    def setUp(self):
        import supervisor

        self.sup = supervisor

    def test_detects_a_running_job(self):
        self.assertEqual(self.sup.running_for("definitely-not-a-character"), [])

    def test_source_enforces_one_actor_per_character(self):
        src = open(os.path.join(RECIPES_DIR, "supervisor.py")).read()
        self.assertIn("kill_for", src)

    def test_source_restarts_from_the_assignment(self):
        src = open(os.path.join(RECIPES_DIR, "supervisor.py")).read()
        self.assertIn("no job running, restarting assignment", src)
