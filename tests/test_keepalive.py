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
