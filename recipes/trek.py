#!/usr/bin/env python3
"""Cross a long distance into ground nobody has mapped, cheapest method first.

Three recipes already cover pieces of travel and none of them covers a journey:

  - `route.py` plans over ground that has already been walked. It answers
    `no_known_route` for anywhere new, which is precisely where a scout goes.
  - `walk.py` sends one long `walkTo` and lets the server path. Fast and right
    for open ground, but it gives up at the first real obstacle and ends the run.
  - `maze.py` steps tile by tile around obstacles. It gets through almost
    anything and it is *slow* -- a scout sent 600 tiles west on maze.py alone
    covered 29 tiles in the time a `walkTo` would have covered several hundred.

So a long trip currently means choosing in advance between "fast but stops at
the first fence" and "gets there tomorrow". This uses all three, in order of
what they cost:

  1. **Plan the whole corridor offline first**, by BFS over the content pack's
     map data. Under a second for a 400x160 corridor, and it is the only step
     that can see a wall before walking into one. A scout striding straight
     west out of Falador stalled against the castle wall; the way around
     starts by going *east*, which no amount of straight-line retrying finds.
  2. **Walk the plan in long legs.** The 459-tile path becomes 19 `walkTo`
     legs, each one the server's own pathfinding over ground already known to
     be open.
  3. **Spend `maze.py` only where reality disagrees with the map.** The map
     over-reports open ground, so some planned tiles are refused live. That
     obstacle -- and only that obstacle -- gets the expensive treatment, then
     the plan is recomputed, because `maze.py` has just written what it
     learned and a fresh plan is therefore a different plan.

That ordering is the whole idea. Most of a journey is open ground, so most of it
should cost one `walkTo`; the expensive method is spent only on the few tiles
that actually need it. `--no-plan` falls back to striding for when there is no
content pack to plan against.

Everything is recorded on the way through, because both underlying recipes
already record: `walk.py`'s leg writes hops to routes.json, and every settled
read feeds the atlas. A scout that walks without recording teaches nobody, which
has happened here before and cost several hundred tiles of exploration.

Usage:
    python3 recipes/trek.py --character scout2 --to 2670,3312 --content ../Content

A trek that cannot close the last gap stops and says where, with the obstacle
written to routes.json as an open problem, rather than looping.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atlas  # noqa: E402
import mapdata  # noqa: E402
import maze  # noqa: E402
import walk  # noqa: E402
from travel import record  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)
DEFAULT_ROUTES = os.path.join(HERE, "routes.json")


def emit(**kw):
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def step_toward(here, goal, stride):
    """A waypoint `stride` tiles along the straight line from here to goal.

    Deliberately naive: the server paths around whatever is in the way, and a
    clever client-side line would just be a second, worse pathfinder.

    This is the fallback for when there is no map data to plan over. Straight
    lines walk into city walls -- see `plan_offline`.
    """
    hx, hz = here
    gx, gz = goal
    dx, dz = gx - hx, gz - hz
    span = max(abs(dx), abs(dz))
    if span <= stride:
        return (gx, gz)
    return (hx + round(dx * stride / span), hz + round(dz * stride / span))


def plan_offline(here, goal, content, margin=200):
    """BFS the whole corridor over map data before taking a single step.

    Striding straight at a distant goal assumes the world between is open, and
    cities are exactly where that assumption breaks: a scout heading west out of
    Falador stalled against the castle wall, because the way around starts by
    going *east*. No amount of straight-line retrying finds that.

    The content pack already knows where the walls are, and BFS over it costs
    under a second for a 400x160 corridor -- far cheaper than discovering one
    wall at a time with a live character. So plan first, walk second.

    The map over-reports open ground, and the reason is worth stating plainly:
    **water and lava are terrain, not locs**, so `mapdata.blocked()` cannot see
    them at all. A route straight across a river looks perfect offline. That is
    the same shape of problem as the Lava Maze, and it is why this unions in
    `maze.py`'s learned-blocked set: those are tiles a live character was
    actually refused, which is the only record of terrain the loc data omits.

    Without that union the plan is a constant -- replanning returns the
    identical route and the trek stalls on the identical tile, which is exactly
    the loop `maze.py`'s own docstring warns about. Measured live: a scout at
    (3028,3390) could walk east, west and north but never south, because the
    reeds south of her were water; the offline plan kept sending her south.

    Returns a list of tiles, or None when the corridor is closed -- which is
    itself worth knowing before committing a character to the trip.
    """
    # The box has to be generous. A margin of 60 was enough to answer "is there
    # roughly a straight way there" and not enough for any route that detours
    # widely -- it reported "no corridor" from (3094,3212) to Ardougne, a trip
    # that exists, because the way around leaves the box. A corridor that is
    # merely wide costs BFS almost nothing; a corridor that is too narrow costs
    # a wrong answer, and a wrong "no route" is indistinguishable from a closed
    # world.
    box = (
        min(here[0], goal[0]) - margin,
        max(here[0], goal[0]) + margin,
        min(here[1], goal[1]) - margin,
        max(here[1], goal[1]) + margin,
    )
    blocked = mapdata.blocked(box[0], box[1], box[2], box[3], content)
    learned = maze.load_learned(maze.DEFAULT_LEARNED)

    # Strictest first: honour everything a live character was refused.
    plan = maze.plan(tuple(here), tuple(goal), blocked | learned, box)
    if plan:
        return plan

    # Nothing got through. Rather than declaring the world closed, drop the
    # learned tiles and plan on map data alone.
    #
    # The learned set believes a single refusal, permanently -- it keeps no
    # counts and nothing ever clears it, unlike the atlas, which requires two
    # refusals and forgets a tile the moment somebody stands on it. So one
    # unlucky probe at a chokepoint seals a corridor for good. Measured: at
    # (2936,3354) a 461-tile route to Ardougne existed on map data and shared
    # exactly ONE tile with the learned set, yet the union returned no route.
    #
    # A plan that ignores a doubtful refusal is worth more than no plan,
    # because walking it re-tests the tile and the walk is what learns.
    plan = maze.plan(tuple(here), tuple(goal), blocked, box)
    if plan:
        emit(plan="relaxed", note="no route honouring learned blocks; map data only")
    return plan


def thin(path, stride):
    """Every `stride`-th tile of a path, plus its end.

    A 459-tile path walked tile by tile is maze.py again. Sampling it turns the
    plan into a handful of long `walkTo` legs that the server paths between,
    which is the fast half of this recipe.
    """
    if not path:
        return []
    picks = path[stride::stride]
    if not picks or picks[-1] != path[-1]:
        picks.append(path[-1])
    return picks


def detour(character, goal, content, budget, min_hp):
    """Hand one obstacle to maze.py, with a bounded budget.

    maze.py is the expensive tool, so it is given a near target rather than the
    whole journey: get *past this fence*, not *go to Ardougne*.
    """
    r = subprocess.run(
        [
            "python3",
            os.path.join(HERE, "maze.py"),
            "--character",
            character,
            "--to",
            "%d,%d" % goal,
            "--pad",
            str(budget),
            "--min-hp",
            str(min_hp),
        ]
        + (["--content", content] if content else []),
        capture_output=True,
        text=True,
        cwd=CLI_DIR,
    )
    last = {}
    for line in (r.stdout or "").splitlines():
        try:
            last = json.loads(line)
        except Exception:
            continue
    return last


def nearest_road(at, content, radius=25):
    """The closest road tile, or None. Roads are the world's own walkways."""
    try:
        box = (at[0] - radius, at[0] + radius, at[1] - radius, at[1] + radius)
        road = mapdata.roads(box[0], box[1], box[2], box[3], content)
        blocked = mapdata.terrain_blocked(box[0], box[1], box[2], box[3], content)
        road -= blocked
        if not road:
            return None
        return min(road, key=lambda t: abs(t[0] - at[0]) + abs(t[1] - at[1]))
    except Exception:
        return None


def diagnose(at, goal, content):
    """Say WHY a trek stuck here, using everything the map knows.

    A scout that reports only "stuck at (2639,3354)" teaches the next scout
    nothing: the coordinate is a fact about one journey, not about the world.
    The next character arrives, tries the same direction, and spends the same
    hour.

    Everything needed to explain it is now readable -- terrain flags, water
    overlays, and the road network -- so a failure can leave behind a reason
    instead of a coordinate. Written after a character spent an hour pinned on
    an Ardougne riverbank with a road three tiles west of her.
    """
    out = {"at": list(at)}
    try:
        box = (at[0] - 12, at[0] + 12, at[1] - 12, at[1] + 12)
        blocked = mapdata.terrain_blocked(box[0], box[1], box[2], box[3], content)
        road = mapdata.roads(box[0], box[1], box[2], box[3], content)
        ov = mapdata.overlay_map(box[0], box[1], box[2], box[3], content)
        ring = [
            (at[0] + dx, at[1] + dz) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
        ]
        out["neighbours_blocked"] = [list(t) for t in ring if t in blocked]
        out["overlays_around"] = sorted({ov[t] for t in ring + [tuple(at)] if t in ov})
        out["water_adjacent"] = any(
            ov.get(t) in mapdata.BLOCKING_OVERLAYS for t in ring
        )
        if road:
            near = min(road, key=lambda t: abs(t[0] - at[0]) + abs(t[1] - at[1]))
            out["nearest_road"] = list(near)
            out["road_distance"] = abs(near[0] - at[0]) + abs(near[1] - at[1])
        out["goal_bearing"] = [goal[0] - at[0], goal[1] - at[1]]
    except Exception as exc:
        out["diagnose_failed"] = str(exc)[:80]
    return out


def leave_scout_note(at, goal, content, legs, detours, replans):
    """Write the diagnosis into the shared atlas, so the next scout inherits it."""
    try:
        note = diagnose(at, goal, content)
        note.update(
            {
                "kind": "trek_stuck",
                "legs": legs,
                "detours": detours,
                "replans": replans,
            }
        )

        def mutate(a):
            a.setdefault("notes", {})["stuck_%d_%d" % (at[0], at[1])] = note

        atlas._update(mutate)
        emit(scout_note=note)
    except Exception as exc:  # a lost note must never end a journey
        emit(warn="could not leave scout note", detail=str(exc)[:80])


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", required=True)
    ap.add_argument("--to", required=True, help="x,z")
    ap.add_argument("--content", default=None)
    ap.add_argument("--stride", type=int, default=25, help="tiles per fast leg")
    ap.add_argument("--tol", type=int, default=3)
    ap.add_argument("--min-hp", type=int, default=0)
    ap.add_argument("--food", default="Lobster")
    ap.add_argument("--legs", type=int, default=120, help="max legs before giving up")
    ap.add_argument("--detour-budget", type=int, default=25)
    ap.add_argument(
        "--no-plan",
        action="store_true",
        help="stride straight at the goal instead of planning over map data",
    )
    ap.add_argument("--replans", type=int, default=6)
    ap.add_argument(
        "--drift",
        type=int,
        default=120,
        help="abandon a plan once it leaves you this many tiles worse than best",
    )
    ap.add_argument(
        "--plan-patience",
        type=int,
        default=10,
        help="plan legs allowed without improving on best before abandoning",
    )
    a = ap.parse_args(argv)

    gx, gz = (int(v) for v in a.to.split(","))
    goal = (gx, gz)

    here, _ = walk.settled(a.character)
    emit(trek="start", at=list(here), goal=list(goal), stride=a.stride)

    best = abs(here[0] - gx) + abs(here[1] - gz)
    detours = 0
    legs_walked = 0
    replans = 0
    stale = 0
    road_rescue_tried = False
    route = []

    def replan(frm):
        """Offline path from here, thinned into walkable legs."""
        if a.no_plan:
            return []
        path = plan_offline(frm, goal, a.content)
        if not path:
            emit(plan="none", frm=list(frm), note="map data shows no corridor")
            return []
        legs = thin(path, a.stride)
        emit(plan="ok", tiles=len(path), legs=len(legs), frm=list(frm))
        return legs

    route = replan(here)

    for _ in range(a.legs):
        here, _ = walk.settled(a.character)
        gap = abs(here[0] - gx) + abs(here[1] - gz)
        if gap <= a.tol:
            emit(
                trek="arrived",
                at=list(here),
                legs=legs_walked,
                detours=detours,
                replans=replans,
            )
            return 0

        # Follow the plan where there is one; otherwise head straight at the goal.
        if route:
            way = route[0]
        else:
            way = step_toward(here, goal, a.stride)

        ok, hops, at = walk.leg(a.character, way, a.min_hp, a.food, calls=4, tol=a.tol)
        # RECORD. walk.leg only *returns* hops -- the writing lives in walk.py's
        # main(), so a recipe that calls leg() directly walks hundreds of tiles
        # and teaches nobody. That is exactly what happened: a character crossed
        # half the world this evening and route.py still answered `off_the_map`,
        # because zero hops within 150 tiles of her had ever been written down.
        #
        # Only hops in routes.json feed route.py, which is the planner a valuable
        # character should be using -- discovery belongs to scouts, and proven
        # roads only exist if somebody wrote them down.
        try:
            record(
                DEFAULT_ROUTES,
                list(here),
                list(way),
                hops,
                [],
                ok,
                stuck_at=None if ok else list(at),
            )
        except Exception as exc:  # recording must never stop the journey
            emit(warn="could not record hops", detail=str(exc)[:80])
        legs_walked += 1
        gap = abs(at[0] - gx) + abs(at[1] - gz)
        emit(
            leg=list(way), ok=ok, at=list(at), gap=gap, hops=len(hops), left=len(route)
        )

        if ok and route:
            route.pop(0)
            if gap < best:
                best, stale = gap, 0
            else:
                # A plan leg succeeded without getting closer. That is normal
                # for a while -- the way out of Falador starts by heading east
                # -- but it is also exactly how a bad plan burns a character.
                stale += 1
                if gap > best + a.drift or stale > a.plan_patience:
                    emit(
                        abandoning_plan=True,
                        gap=gap,
                        best=best,
                        stale=stale,
                        note="plan walked away from the goal without returning",
                    )
                    route = []
                    replans += 1
                    if replans <= a.replans:
                        route = replan(at)
                    continue
            continue
        if gap < best:
            best, stale = gap, 0
            continue

        # The fast path stopped closing. Spend the expensive method here only.
        detours += 1
        emit(detour=detours, around=list(way), budget=a.detour_budget)
        res = detour(a.character, way, a.content, a.detour_budget, a.min_hp)
        after, _ = walk.settled(a.character)
        gap = abs(after[0] - gx) + abs(after[1] - gz)
        emit(detour_result=res.get("final") or res, at=list(after), gap=gap)

        if gap < best:
            best = gap
            if route:
                route.pop(0)
            continue

        # Reality disagrees with the map here. maze.py has just written what it
        # learned to blocked_tiles.json, so a fresh plan is a different plan --
        # replanning without learning is the loop this deliberately avoids.
        atlas.observe(
            walk.state(a.character),
            stood=list(after),
            refused=list(way),
            reason="trek leg and detour both failed",
        )
        replans += 1
        if replans > a.replans:
            emit(
                trek="stuck",
                at=list(after),
                gap=gap,
                legs=legs_walked,
                detours=detours,
                replans=replans,
                note="leg, detour and replan all failed to close the gap",
            )
            leave_scout_note(after, goal, a.content, legs_walked, detours, replans)
            # Before giving up, head for the road. The world was built to be
            # walked on roads, and a stuck trek is usually stuck in the scrub
            # beside one -- a character pinned on an Ardougne riverbank for an
            # hour had road three tiles west of her the whole time. Road is
            # overlay 10, carrying 158 walked tiles against 5 refusals, the
            # most reliable surface there is.
            if not road_rescue_tried:
                road_rescue_tried = True
                spot = nearest_road(after, a.content)
                if spot and spot != after:
                    path = plan_offline(after, spot, a.content)
                    if path:
                        emit(
                            road_rescue=list(spot),
                            tiles=len(path),
                            note="heading for the road, then resuming",
                        )
                        route = thin(path, a.stride)
                        best = abs(after[0] - goal[0]) + abs(after[1] - goal[1])
                        stale = 0
                        replans = 0
                        continue
            return 1
        emit(replanning=replans, frm=list(after))
        route = replan(after)

    final, _ = walk.settled(a.character)
    emit(
        trek="out_of_legs",
        at=list(final),
        gap=abs(final[0] - gx) + abs(final[1] - gz),
        legs=legs_walked,
        detours=detours,
        replans=replans,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
