#!/usr/bin/env python3
"""Walk somewhere far by planning over tiles this world has already walked.

`travel.py` hops greedily toward its target and stops when nothing gets
closer. That is right for a short walk and hopeless for a long one: the
terrain here has hard boundaries with no crossable loc anywhere near them, so
"head that way" reliably ends at a wall a fixed distance from the goal, and
whoever is watching then hand-picks intermediate waypoints out of
`routes.json` and tries again. That hand-picking was the single most repeated
piece of steering this project needed, and it does not need a person or a
model -- `routes.json` already contains the map.

This plans over it. Nodes are tiles a character has actually stood on, edges
are hops that actually happened, and the walk is the shortest chain of those
through to the destination, handed to `travel.py` one leg at a time.

    uv run recipes/route.py --character gorruk --to 3252,3404
    uv run recipes/route.py --character sylas --landmark rune_shop

## open_problems is map data, not a list of impossible moves

This is the part that makes it work. `travel.py` files a failed *journey*
under `open_problems`, but the `hops` inside that record are movements that
really happened -- the character was at each of those tiles in turn. Only the
overall trip failed.

Built from `confirmed_paths` alone the graph has 1,301 edges in 5 disconnected
components, and Lumbridge and Varrock sit in different ones: there is no route
between them, which is plainly false, since a character has stood at Aubury's
door. Adding the hops recorded inside `open_problems` contributes 1,529 more
edges -- more than the confirmed set -- and the graph becomes connected, with
the courtyard and Aubury's in the same component.

So both buckets are read, and edges are weighted by where they came from:
a hop inside a failed journey is real, but a hop inside a successful one is
better evidence, so confirmed edges are preferred when both exist.

Output is one JSON object per line: a `plan` line with the chosen waypoints, a
`leg` line per hop with `travel.py`'s own output forwarded, then a final `done`
line. Exit status is 0 on arrival, 2 when a leg stalled (the plan is reported
so the next run can see where), and 1 for a usage error or an unreachable
destination.
"""

from __future__ import annotations

import argparse
import collections
import heapq
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from travel import (  # noqa: E402
    DEFAULT_ROUTES,
    Stop,
    emit,
    load_routes,
    pos_of,
    read_state,
)

HERE = os.path.dirname(os.path.abspath(__file__))
TRAVEL = os.path.join(HERE, "travel.py")

# A hop recorded inside a successful journey is better evidence than one
# recorded inside a failed journey, though both really happened. The
# difference only breaks ties: it must not be big enough to send a walk the
# long way round through confirmed tiles when a shorter known hop exists.
CONFIRMED_WEIGHT = 1.0
ATTEMPTED_WEIGHT = 1.6


def as_point(value):
    if isinstance(value, dict):
        x, z = value.get("x"), value.get("z")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x, z = value[0], value[1]
    else:
        return None
    if not isinstance(x, int) or not isinstance(z, int):
        return None
    return (x, z)


# A hop longer than this was never a single walk: walkTo caps at ~7-8 tiles,
# and the one known exception (the dialog-gated border, which behaves like a
# teleport) is 6-9. Anything larger is an artefact of how a journey was
# recorded, not a movement, and one such phantom edge is enough to make every
# plan end in an impossible leap.
MAX_HOP = 14


def sequences(routes: dict, bucket: str, reached_target: bool):
    """Every recorded journey in `bucket`, as a list of tiles in order.

    `reached_target` says whether the record's `to` field is somewhere the
    character actually got to. For `confirmed_paths` it is. For
    `open_problems` it is emphatically NOT -- `to` there is the destination the
    journey FAILED to reach, so the edge from the last real hop to it never
    happened. Including it invents a hop straight to the goal, which a planner
    will then happily route through: every plan built before this was excluded
    ended with a single 135-tile stride from (3253,3269) to Aubury's door.
    """
    for record in routes.get(bucket) or []:
        if not isinstance(record, dict):
            continue
        tiles = [as_point(record.get("from"))]
        tiles += [as_point(hop) for hop in record.get("hops") or []]
        if reached_target:
            tiles.append(as_point(record.get("to")))
        yield [t for t in tiles if t]


def build_graph(routes: dict) -> dict:
    """Tiles that have been stood on, linked by hops that have happened."""
    graph: dict = collections.defaultdict(dict)
    for bucket, weight, reached in (
        ("open_problems", ATTEMPTED_WEIGHT, False),
        ("confirmed_paths", CONFIRMED_WEIGHT, True),
    ):
        # confirmed second, so it overwrites the attempted weight for any hop
        # that appears in both.
        for tiles in sequences(routes, bucket, reached):
            for a, b in zip(tiles, tiles[1:]):
                if a == b:
                    continue
                span = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
                if span > MAX_HOP:
                    continue
                cost = span * weight
                for u, v in ((a, b), (b, a)):
                    # Recorded one way, walkable the other: every blocker seen
                    # here so far (gate, door, stile, toll dialog) opens from
                    # both sides. A one-way graph would refuse most return trips.
                    if v not in graph[u] or cost < graph[u][v]:
                        graph[u][v] = cost
    return graph


def nearest(graph: dict, target: tuple, limit: int = 60):
    """The known tile closest to `target`, if one is close enough to be useful."""
    best, best_gap = None, None
    for node in graph:
        gap = max(abs(node[0] - target[0]), abs(node[1] - target[1]))
        if best_gap is None or gap < best_gap:
            best, best_gap = node, gap
    if best_gap is not None and best_gap > limit:
        return None, best_gap
    return best, best_gap


def shortest(graph: dict, source: tuple, target: tuple):
    """Dijkstra over recorded hops. Returns the tile chain, or None."""
    if source == target:
        return [source]
    seen = {source: 0.0}
    queue = [(0.0, source, [source])]
    while queue:
        cost, node, chain = heapq.heappop(queue)
        if node == target:
            return chain
        if cost > seen.get(node, float("inf")):
            continue
        for neighbour, step in graph[node].items():
            through = cost + step
            if through < seen.get(neighbour, float("inf")):
                seen[neighbour] = through
                heapq.heappush(queue, (through, neighbour, chain + [neighbour]))
    return None


def thin(chain: list, stride: int) -> list:
    """Drop tiles travel.py would cross on its own.

    A chain straight out of the graph can be a hundred one-tile steps, and
    handing each to travel.py spends a process per tile. Keep a waypoint
    roughly every `stride` tiles, plus every point where the direction
    changes sharply, since those are where the blockers are.
    """
    if len(chain) <= 2:
        return chain
    kept = [chain[0]]
    for index in range(1, len(chain) - 1):
        previous, here, following = chain[index - 1], chain[index], chain[index + 1]
        gap = max(
            abs(here[0] - kept[-1][0]),
            abs(here[1] - kept[-1][1]),
        )
        turn = (previous[0] - here[0]) * (here[1] - following[1]) != (
            previous[1] - here[1]
        ) * (here[0] - following[0])
        if gap >= stride or turn:
            kept.append(here)
    kept.append(chain[-1])
    return kept


def walk_leg(args, x: int, z: int) -> tuple:
    """Hand one leg to travel.py, forwarding its lines as they arrive."""
    command = [
        sys.executable,
        TRAVEL,
        "--character",
        args.character,
        "--x",
        str(x),
        "--z",
        str(z),
        "--min-hp",
        str(args.min_hp),
        "--patience",
        str(args.patience),
        "--probe-radius",
        str(args.probe_radius),
        "--routes",
        args.routes,
    ]
    last = {}
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
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
    return last.get("done") or "no_outcome", code


def run(args) -> str:
    routes = load_routes(args.routes)
    if args.landmark:
        landmarks = routes.get("landmarks") or {}
        if args.landmark not in landmarks:
            raise Stop("unknown_landmark", "known: %s" % sorted(landmarks))
        target = as_point(landmarks[args.landmark])
    else:
        target = (args.x, args.z)

    graph = build_graph(routes)
    if not graph:
        raise Stop("no_map", "%s records no walked hops to plan over" % args.routes)

    here = pos_of(read_state(args.character))
    start, start_gap = nearest(graph, here)
    finish, finish_gap = nearest(graph, target)
    if start is None:
        raise Stop(
            "off_the_map",
            "no walked tile within %d of %s; walk somewhere known first"
            % (start_gap, here),
        )
    if finish is None:
        raise Stop(
            "unmapped_destination",
            "nothing walked within %d of %s, so there is no route to plan; "
            "explore toward it with travel.py and this will work next time"
            % (finish_gap, target),
        )

    chain = shortest(graph, start, finish)
    if chain is None:
        raise Stop(
            "no_known_route",
            "%s and %s are both on the map but not connected by any recorded "
            "hop; the connecting stretch has never been walked" % (here, target),
        )

    waypoints = thin(chain, args.stride)
    if waypoints and waypoints[-1] != target:
        waypoints.append(target)
    emit(
        {
            "plan": [list(w) for w in waypoints],
            "from": list(here),
            "to": list(target),
            "graph": {"nodes": len(graph), "chain": len(chain)},
        }
    )

    for index, (x, z) in enumerate(waypoints, 1):
        emit({"leg": index, "of": len(waypoints), "target": [x, z]})
        outcome, _ = walk_leg(args, x, z)
        if outcome in ("died", "low_hp"):
            raise Stop(outcome, "stopped on leg %d of %d" % (index, len(waypoints)))
        if outcome != "arrived":
            # One stalled leg does not condemn the plan: the next waypoint may
            # be reachable from where this one gave up, and travel.py has just
            # filed what blocked it. Push on rather than abandoning the trip.
            emit({"leg_stalled": index, "outcome": outcome})

    final = pos_of(read_state(args.character))
    gap = max(abs(final[0] - target[0]), abs(final[1] - target[1]))
    if gap <= args.close_enough:
        return "arrived"
    raise Stop(
        "short_of_target",
        "ended at %s, %d tiles from %s; the plan was %s"
        % (final, gap, target, [list(w) for w in waypoints]),
    )


def parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk somewhere far by planning over tiles already walked."
    )
    parser.add_argument("--character", required=True)
    target = parser.add_argument_group("destination (one of)")
    target.add_argument("--landmark", help="A name from --routes' landmarks")
    target.add_argument("--to", help="X,Z")
    parser.add_argument("--routes", default=DEFAULT_ROUTES)
    parser.add_argument(
        "--stride",
        type=int,
        default=12,
        help="Roughly how many tiles between planned waypoints; turns always "
        "keep one, since that is where blockers are (default 12)",
    )
    parser.add_argument(
        "--close-enough",
        type=int,
        default=6,
        help="Tiles from the destination that still counts as arrived",
    )
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--probe-radius", type=int, default=25)
    parser.add_argument("--min-hp", type=int, default=0)
    args = parser.parse_args(argv)
    if not args.landmark and not args.to:
        parser.error("give --landmark or --to X,Z")
    args.x = args.z = None
    if args.to:
        try:
            x, z = args.to.split(",")
            args.x, args.z = int(x), int(z)
        except ValueError:
            parser.error("--to takes X,Z")
    return args


def main(argv) -> int:
    args = parse(argv)
    try:
        outcome = run(args)
    except Stop as stop:
        emit({"done": stop.reason, "detail": stop.detail})
        return 1 if stop.reason in ("no_map", "unknown_landmark") else 2
    except KeyboardInterrupt:
        emit({"done": "interrupted", "detail": "the character keeps its position"})
        return 2
    emit({"done": outcome})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
