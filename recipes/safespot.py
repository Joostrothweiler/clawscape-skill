#!/usr/bin/env python3
"""Where can I stand to shoot this thing while it cannot reach me?

`references/safespotting.md` used to answer that with terrain: find a tile the
monster cannot *path* to. Run over every moss giant camp in the world, that
search returns exactly one usable tile, and it is on Crandor, behind a quest.
The method is not wrong, it is just nearly always empty, and it sent an agent
looking for lakes when the answer was in the npc config all along.

**The mechanism is the leash.** Every NPC carries `maxrange` in `all.npc` -- the
furthest it will go from the tile it spawned on. A moss giant's is 5. A guard's
is 7. A goblin's is 17. It is not a tendency, it is a wall the monster builds
around its own spawn, and it does not care about terrain at all.

    moss giant maxrange 5   +   oak longbow attackrange 10   =   a 3-tile window

Stand 8, 9 or 10 tiles from a moss giant's spawn tile with clear line of sight
and it can neither reach you nor leave. That is a safespot in open grass, which
is why the terrain search kept coming up empty: it was looking for the wrong
thing.

Two facts hold it up, both read from the world's own scripts and then measured
live against Varrock guards on 2026-09-16:

  - `player_combat.rs2` fires the attack **from where you stand** whenever the
    target is inside the weapon's `attackrange`; `p_aprange` only walks you in
    when it is further. `attackrange` is an obj param: **longbows 10, shortbows
    7**, autocast magic 10 -- so the reference's "measured 9" was one tile short
    of a number that was written down.
  - Line of sight decides the rest. Every attack issued with a clear line and a
    target inside range moved the character **zero tiles**; every attack with a
    blocked line walked her in, 4 to 16 tiles. That is the whole difference
    between a safespot and a mauling, and it is invisible from the tile alone.

So a candidate here needs all three: inside `attackrange`, clear line of sight,
and outside the leash circle of **every** hostile spawn nearby -- not just the
one being shot. The third is the one that bites: a tile 8 tiles from your giant
can sit 4 tiles from its neighbour, and the neighbour is the one that kills you.

    python3 recipes/safespot.py --npc mossgiant --range 10

Ranking is by how much slack the tile has, because the leash is exact and the
character's own position is not. One attack in six still walked her in with a
clear line, so a hunt loop must re-assert the tile after every attack -- which
is free here, since stepping back outside the leash breaks contact for good.
"""

import argparse
import json
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapdata  # noqa: E402

NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))
# Diagonals matter: a monster that can step diagonally reaches tiles a
# four-way BFS says it cannot, and over-reporting safety is the error that
# gets a Defence-1 character killed. Both are computed; the strict one wins.
DIAGONALS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def terrain_and_locs(x_lo, x_hi, z_lo, z_hi, level, base, strict=False):
    """Walkable tiles, and separately the things that block SIGHT.

    These are not the same set, and conflating them is what makes a safespot
    search useless. `player_combat.rs2` fires the attack from where you stand
    whenever the target is inside the weapon's `attackrange`; it only walks you
    in when the target is further away. So the question a safespot has to
    answer is not "can I reach it" but "can I see it while it cannot walk to
    me" -- and the two are blocked by different things.

    **Water, lava and cliffs stop a walker and not an arrow.** That is the
    whole mechanism: shooting across a river is a safespot, standing behind a
    wall is not.

    The two error directions are not symmetric, which decides what goes in
    each set. Over-blocking the monster's movement **invents** safespots: a
    giant the model thinks is fenced in walks out and kills you. Under-blocking
    only misses some. So movement uses geometry the world actually states --
    the terrain flags and locs that occupy a whole tile -- and deliberately
    NOT `mapdata.blocked()`'s keyword heuristic, which that module documents as
    over-reporting by 53 tiles in 847. `--strict` adds it back for a planner
    that would rather route around a wall than through one.
    """
    terrain = set(mapdata.terrain_blocked(x_lo, x_hi, z_lo, z_hi, base))
    solids = set(mapdata.solid_tiles(x_lo, x_hi, z_lo, z_hi, level, base))
    extra = set()
    if strict:
        extra = {(x, z) for x, z, *_ in mapdata.blocked(x_lo, x_hi, z_lo, z_hi, base)}
    walk = {
        (x, z)
        for x in range(x_lo, x_hi + 1)
        for z in range(z_lo, z_hi + 1)
        if (x, z) not in terrain and (x, z) not in solids and (x, z) not in extra
    }
    # Sight is stopped by things that fill a tile, never by water.
    return walk, solids


def line_of_sight(a, b, solids, edges):
    """Can an arrow get from a to b? Bresenham, blocked by walls and solids."""
    x0, z0 = a
    x1, z1 = b
    dx, dz = abs(x1 - x0), abs(z1 - z0)
    sx = 1 if x0 < x1 else -1
    sz = 1 if z0 < z1 else -1
    err = dx - dz
    x, z = x0, z0
    while (x, z) != (x1, z1):
        e2 = 2 * err
        nx, nz = x, z
        if e2 > -dz:
            err -= dz
            nx += sx
        if e2 < dx:
            err += dx
            nz += sz
        # A diagonal step crosses two edges; both must be open.
        if nx != x and nz != z:
            if ((x, z), (nx, z)) in edges and ((x, z), (x, nz)) in edges:
                return False
        elif ((x, z), (nx, nz)) in edges:
            return False
        x, z = nx, nz
        if (x, z) == (x1, z1):
            break
        if (x, z) in solids:
            return False
    return True


def reachable_from(start, walk, edges, diagonal=True):
    """Every tile a walker at `start` can get to, respecting wall edges."""
    if start not in walk:
        # A spawn tile the map calls blocked is a map error, not an empty
        # reachable set. Treating it as empty would declare the whole band
        # safe, which is the most dangerous thing this function could return.
        walk = walk | {start}
    steps = NEIGHBOURS + DIAGONALS if diagonal else NEIGHBOURS
    seen = {start}
    q = deque([start])
    while q:
        x, z = q.popleft()
        for dx, dz in steps:
            n = (x + dx, z + dz)
            if n in seen or n not in walk:
                continue
            if ((x, z), n) in edges:
                continue
            seen.add(n)
            q.append(n)
    return seen


def component_size(tile, walk, edges, cap=4000):
    return len(reachable_from(tile, walk, edges)) if tile in walk else 0


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def npc_configs(base):
    """name -> {maxrange, size, vislevel} from the world's own npc config."""
    path = os.path.join(base, "scripts", "_unpack", "all.npc")
    out = {}
    name = None
    for line in open(path):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1]
            out[name] = {
                "maxrange": None,
                "size": 1,
                "vislevel": None,
                "attackable": False,
            }
        elif name and "=" in line:
            k, v = line.split("=", 1)
            if k in ("maxrange", "size", "vislevel") and v.strip().isdigit():
                out[name][k] = int(v)
            elif k.startswith("op") and v.strip() == "Attack":
                out[name]["attackable"] = True
    return out


def leash_reach(spawn, cfg):
    """How close to a given tile this spawn can ever get.

    `maxrange` is measured from the spawn tile, and a size-2 npc occupies a
    2x2 block, so it can put a corner one tile further than its origin
    suggests. Rounded the unsafe way on purpose: a safespot computed one tile
    too tight is a safespot that does not work.
    """
    return (cfg.get("maxrange") if cfg.get("maxrange") is not None else 64) + max(
        1, cfg.get("size") or 1
    )


def solve(spawn, others, walk, sight, edges, weapon_range, cfgs, aggro_cap=None):
    """Stand-tiles that can shoot `spawn` while nothing in `others` can reach.

    Note the tile must be one the target COULD path to. That is the opposite of
    what this function looked for in its first version, and the inversion was
    paid for live: twelve attacks on a moss giant across a dungeon wall, all
    inside bow range, all answering `unrouted - ap-range attempt` for zero xp
    and zero damage taken. A barrier that stops the monster stops the attack.
    The tile has to be somewhere it is willing to go and merely not allowed to.
    """
    target_cfg = cfgs.get(spawn[0], {})
    # Same pathing component as the spawn: attacks need a route, not a line.
    connected = reachable_from(spawn[1], walk, edges)
    out = []
    for p in walk:
        if p not in connected:
            continue
        d = chebyshev(p, spawn[1])
        if d > weapon_range:
            continue
        # Outside the target's own leash, with a tile of slack for our own
        # position drifting, and outside everything else's.
        if d <= leash_reach(spawn[1], target_cfg):
            continue
        if not line_of_sight(p, spawn[1], sight, edges):
            continue
        threats = []
        for name, g in others:
            if (name, g) == spawn:
                continue
            cfg = cfgs.get(name, {})
            # A fishing spot cannot chase anybody. Only things the world gives
            # an Attack option are threats; counting shopkeepers and sheep as
            # hazards made every tile look compromised.
            if not cfg.get("attackable"):
                continue
            # A monster that will not aggro only matters if we attack it, and
            # we do not. vislevel*2 is the usual threshold; it is unconfirmed
            # here, so it only downgrades a threat, never erases one.
            if chebyshev(p, g) <= leash_reach(g, cfg):
                passive = (
                    aggro_cap is not None
                    and cfg.get("vislevel") is not None
                    and cfg["vislevel"] * 2 < aggro_cap
                )
                threats.append(
                    {"name": name, "x": g[0], "z": g[1], "likely_passive": passive}
                )
        slack = d - leash_reach(spawn[1], target_cfg)
        out.append(
            {
                "stand": [p[0], p[1]],
                "target": [spawn[1][0], spawn[1][1]],
                "npc": spawn[0],
                "range": d,
                "leash_slack": slack,
                "threatened_by": [t for t in threats if not t["likely_passive"]],
                "passive_in_reach": [t["name"] for t in threats if t["likely_passive"]],
            }
        )
    out.sort(
        key=lambda r: (
            len(r["threatened_by"]),
            -r["leash_slack"],
            len(r["passive_in_reach"]),
        )
    )
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--npc", help="npc name as it appears in npc.pack, e.g. mossgiant")
    ap.add_argument("--at", help="x,z of one specific spawn to solve against")
    ap.add_argument("--range", type=int, default=10, help="weapon attackrange")
    ap.add_argument("--radius", type=int, default=32, help="band half-width to model")
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--content", default=None)
    ap.add_argument(
        "--combat-level",
        type=int,
        default=None,
        help="ours; marks spawns whose vislevel*2 is below it as likely passive",
    )
    ap.add_argument("--limit", type=int, default=6)
    a = ap.parse_args(argv)

    base = mapdata._content(a.content)
    cfgs = npc_configs(base)
    idname = mapdata.names(base, "npc.pack")
    ids = {v: k for k, v in idname.items()}

    if a.at:
        x, z = (int(v) for v in a.at.split(","))
        spawns = [(a.npc or "target", (x, z))]
    elif a.npc:
        if a.npc not in ids:
            print(json.dumps({"error": "no such npc", "npc": a.npc}))
            return 2
        spawns = [
            (a.npc, (x, z))
            for x, z, lvl in mapdata.spawns(ids[a.npc], "NPC", base)
            if lvl == a.level
        ]
    else:
        ap.error("need --npc or --at")

    cfg = cfgs.get(a.npc or "", {})
    print(
        json.dumps(
            {
                "npc": a.npc,
                "maxrange": cfg.get("maxrange"),
                "size": cfg.get("size"),
                "vislevel": cfg.get("vislevel"),
                "weapon_range": a.range,
                "window": "%d..%d tiles from spawn"
                % (leash_reach((0, 0), cfg) + 1, a.range),
                "spawns": len(spawns),
            }
        )
    )

    camps = []
    for name, g in spawns:
        for c in camps:
            if any(chebyshev(g, o) <= a.radius for _, o in c):
                c.append((name, g))
                break
        else:
            camps.append([(name, g)])

    for camp in camps:
        xs = [g[0] for _, g in camp]
        zs = [g[1] for _, g in camp]
        x_lo, x_hi = min(xs) - a.radius, max(xs) + a.radius
        z_lo, z_hi = min(zs) - a.radius, max(zs) + a.radius
        walk, solids = terrain_and_locs(x_lo, x_hi, z_lo, z_hi, a.level, base)
        edges = mapdata.wall_edges(x_lo, x_hi, z_lo, z_hi, a.level, base)
        terrain = set(mapdata.terrain_blocked(x_lo, x_hi, z_lo, z_hi, base))
        keyword = {(x, z) for x, z, *_ in mapdata.blocked(x_lo, x_hi, z_lo, z_hi, base)}
        # Sight is stopped by anything filling a tile. Water is not.
        sight = solids | (keyword - terrain)
        others = [
            (nm, (x, z))
            for x, z, _rid, nm in mapdata.band(
                x_lo, x_hi, z_lo, z_hi, "NPC", a.level, base
            )
        ]
        best = []
        for spawn in camp:
            rows = solve(
                spawn, others, walk, sight, edges, a.range, cfgs, a.combat_level
            )
            clean = [r for r in rows if not r["threatened_by"]]
            best.extend(clean)
            print(
                json.dumps(
                    {
                        "camp": [x_lo, x_hi, z_lo, z_hi],
                        "spawn": list(spawn[1]),
                        "candidates": len(rows),
                        "unthreatened": len(clean),
                    }
                )
            )
        best.sort(key=lambda r: (-r["leash_slack"], len(r["passive_in_reach"])))
        for r in best[: a.limit]:
            print(json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
