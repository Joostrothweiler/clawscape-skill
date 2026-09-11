"""Offline checks for recipes/travel.py's progress test: nothing here reaches
a world. See progress_check's own docstring for why this exists -- the first
version of the recipe checked only "did the last hop move the character," and
that let it bounce between two tiles in a fenced pocket for 20+ rounds in
live play, each hop individually "successful" while the trip made no
progress at all. These are the two live cases that bug should have caught."""

from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


travel = load("travel", "recipes/travel.py")


class ProgressCheck(unittest.TestCase):
    def test_a_hop_toward_the_target_is_progress(self):
        progressing, cycling, dist = travel.progress_check(
            new_pos=(3215, 3225),
            cur=(3222, 3218),
            target=(3210, 3424),
            best_dist=travel.chebyshev((3222, 3218), (3210, 3424)),
            visited=[(3222, 3218)],
        )
        self.assertTrue(progressing)
        self.assertFalse(cycling)

    def test_bouncing_between_two_tiles_is_not_progress(self):
        """The exact live failure: walkTo resolves to whichever of two
        reachable tiles is nearest, alternating every call. Each hop moves
        the character, so a "did position change" check alone reports
        success forever."""
        a, b, target = (3221, 3225), (3216, 3230), (3210, 3424)
        best_dist = travel.chebyshev(a, target)
        visited = [a]
        for landing in (b, a, b, a):
            progressing, cycling, dist = travel.progress_check(
                landing, visited[-1], target, best_dist, visited
            )
            visited.append(landing)
            if progressing:
                best_dist = dist
        self.assertFalse(progressing)
        self.assertTrue(cycling)

    def test_moving_further_from_the_target_is_not_progress(self):
        """A sidestep that changes position without a prior best_dist update
        should not itself count as progress -- only the next hop that
        actually closes the distance should."""
        progressing, cycling, dist = travel.progress_check(
            new_pos=(3222, 3200),  # z moved away from the target's z=3424
            cur=(3222, 3218),
            target=(3210, 3424),
            best_dist=travel.chebyshev((3222, 3218), (3210, 3424)),
            visited=[(3222, 3218)],
        )
        self.assertFalse(cycling)
        self.assertFalse(progressing)

    def test_no_movement_at_all_is_not_progress(self):
        # cur itself is always in visited, so this also reports cycling=True
        # -- that's fine, only progressing being False is the contract here.
        progressing, cycling, dist = travel.progress_check(
            new_pos=(3222, 3218),
            cur=(3222, 3218),
            target=(3210, 3424),
            best_dist=travel.chebyshev((3222, 3218), (3210, 3424)),
            visited=[(3222, 3218)],
        )
        self.assertFalse(progressing)


if __name__ == "__main__":
    unittest.main()


class HopLadder(unittest.TestCase):
    """Why: a single fixed hop length cannot walk a corridor narrower than
    itself -- the requested tile lands in rock and walkTo is refused, which
    reads identically to a wall. Live in the Varrock sewers that produced the
    same tile across eight consecutive waypoint calls."""

    def test_longest_hop_is_tried_first(self):
        # Open ground must not pay for the corridor case.
        self.assertEqual(travel.hop_ladder(7)[0], 7)

    def test_ladder_halves_down_to_one_tile(self):
        self.assertEqual(travel.hop_ladder(8), [8, 4, 2, 1])

    def test_ladder_always_ends_at_one(self):
        for size in (1, 2, 3, 7, 12, 20):
            self.assertEqual(travel.hop_ladder(size)[-1], 1, size)

    def test_ladder_is_strictly_decreasing(self):
        ladder = travel.hop_ladder(12)
        self.assertEqual(ladder, sorted(set(ladder), reverse=True))

    def test_a_short_hop_still_heads_at_the_target(self):
        # The narrowed retry must keep the same heading, not wander.
        cur, target = (3247, 9869), (3200, 9869)
        self.assertEqual(travel.step_toward(cur, target, 7), (3240, 9869))
        self.assertEqual(travel.step_toward(cur, target, 1), (3246, 9869))

    def test_step_never_overshoots_a_near_target(self):
        cur, target = (3247, 9869), (3245, 9869)
        self.assertEqual(travel.step_toward(cur, target, 7), target)
