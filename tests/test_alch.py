"""Alchemy's failures are silent, so the guards against them are the tests.

Every cast returns `success: true`. A run that is doing nothing at all looks
exactly like a run that is working, so the two things that decide whether it
works -- the staff being worn, and the feedstock count -- are checked here.
"""

import json
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes"
    ),
)

import alch  # noqa: E402

# A real state read. The staff's only option is Wield, at opIndex 2, sitting at
# position 0 of the list. Sending the position plus one sends 1, and nothing
# happens.
STAFF_ROW = {
    "slot": 0,
    "name": "Staff of fire",
    "optionsWithIndex": [{"text": "Wield", "opIndex": 2}],
}


class FakeWalk:
    def __init__(self, states):
        self.states = list(states)
        self.calls = []

    def cli(self, ch, *args):
        self.calls.append(args)
        return ""

    def state(self, ch):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


class WieldStaff(unittest.TestCase):
    def setUp(self):
        self._walk = alch.walk

    def tearDown(self):
        alch.walk = self._walk

    def test_sends_the_options_own_opindex(self):
        equipped = {"inventory": [], "equipment": [{"name": "Staff of fire"}]}
        alch.walk = FakeWalk([equipped])
        d = {"inventory": [STAFF_ROW], "equipment": []}
        self.assertTrue(alch.wield_staff("arete", d))
        acts = [c for c in alch.walk.calls if c[0] == "act"]
        payload = json.loads(acts[0][-1])
        self.assertEqual(payload["optionIndex"], 2)

    def test_reports_failure_when_the_staff_stays_in_the_pack(self):
        """The bug that cost 30 casts: dispatched fine, never equipped."""
        alch.walk = FakeWalk([{"inventory": [STAFF_ROW], "equipment": []}])
        d = {"inventory": [STAFF_ROW], "equipment": []}
        self.assertFalse(alch.wield_staff("arete", d))

    def test_already_worn_needs_no_call(self):
        alch.walk = FakeWalk([{}])
        d = {"inventory": [], "equipment": [{"name": "Staff of fire"}]}
        self.assertTrue(alch.wield_staff("arete", d))
        self.assertEqual(alch.walk.calls, [])


class Feedstock(unittest.TestCase):
    def test_a_stack_is_counted_by_its_amount_not_its_slot(self):
        """One slot holding 200 feathers is 200 casts, not one."""
        d = {"inventory": [{"slot": 2, "name": "Feather", "count": 200}]}
        self.assertEqual(alch.stack(d, "Feather"), 200)
        self.assertEqual(alch.count(d, "Feather"), 1)

    def test_non_stackables_still_add_up(self):
        d = {
            "inventory": [{"slot": i, "name": "Lobster", "count": 1} for i in range(9)]
        }
        self.assertEqual(alch.stack(d, "Lobster"), 9)


class MessageLog(unittest.TestCase):
    def test_last_message_is_what_the_canary_reports(self):
        d = {"gameMessages": [{"text": "a"}, {"text": "not enough Fire Runes"}]}
        self.assertEqual(alch.last_message(d), "not enough Fire Runes")

    def test_no_messages_is_not_a_crash(self):
        self.assertEqual(alch.last_message({}), "no message")


if __name__ == "__main__":
    unittest.main()
