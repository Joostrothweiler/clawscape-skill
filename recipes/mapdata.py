#!/usr/bin/env python3
"""Query the world's own map files: where does a thing spawn, what is in a band.

`references/world_data.md` explains that this world runs LostCityRS content and
that a question like "where do red dragons spawn" has an exact answer sitting in
a file. This is that lookup, as a library other recipes import and as a CLI.

    git clone --depth 1 --branch 225 https://github.com/LostCityRS/Content.git

Point `--content` (or $CLAWSCAPE_CONTENT) at the clone.

Two warnings that cost other agents real time, repeated here because this module
is where they bite:

  - **The loc files over-report open ground.** Lava, water and cliffs are not
    locs, so "no wall in the LOC data" does NOT mean walkable. The useful
    asymmetry is that *absence of a gate* is meaningful (there is nothing to
    open) while absence of a wall is not.

    **But the terrain is not unknowable** -- it is in the MAP section of the
    same files, which nothing here read until 2026-09-13. Each row is
    `level x z: h<height> f<flags> u<underlay>`, and **flag bit 1 means the
    tile is blocked**. Checked against live ground truth: bit 1 appears on
    **84.7%** of tiles a character was actually refused and only **2.9%** of
    tiles a character actually stood on. Use `terrain_blocked()`, which is
    unioned into `blocked()` automatically.
  - **Many locs have no name.** The Wilderness fence gates are `loc_1596` /
    `loc_1597` with no entry in `loc.pack`, so grepping for "gate" finds
    nothing and invites the conclusion that no opening exists. Use
    `distinct_names()` and read the list rather than searching for the word you
    expect.
"""

import argparse
import io
import json
import os
import re
from collections import Counter

DEFAULT_CONTENT = os.environ.get("CLAWSCAPE_CONTENT", "Content")
ROW = re.compile(r"^m(\d+)_(\d+)\.jm2$")


def _content(path=None):
    base = path or DEFAULT_CONTENT
    if not os.path.isdir(os.path.join(base, "maps")):
        raise SystemExit(
            f"no maps/ under {base!r}; clone the content pack and pass --content"
        )
    return base


def names(base, packfile):
    """id -> name from pack/loc.pack or pack/npc.pack. Missing ids have no name."""
    out = {}
    p = os.path.join(base, "pack", packfile)
    if not os.path.isfile(p):
        return out
    for line in open(p, errors="ignore"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            if k.isdigit():
                out[int(k)] = v
    return out


def _rows(base, section):
    """Yield (worldX, worldZ, level, id) for every row of a section.

    Rows read `level x z: id [angle]`, and world coords are mapX*64+x,
    mapZ*64+z. Reading the head as `x z level` produces plausible, wrong tiles.
    """
    mapdir = os.path.join(base, "maps")
    header = "==== " + section
    for fn in os.listdir(mapdir):
        m = ROW.match(fn)
        if not m:
            continue
        mx, mz = int(m.group(1)), int(m.group(2))
        inside = False
        for line in open(os.path.join(mapdir, fn), errors="ignore"):
            if line.startswith(header):
                inside = True
                continue
            if line.startswith("===="):
                inside = False
                continue
            if not inside or ":" not in line:
                continue
            head, tail = line.split(":", 1)
            hp, parts = head.split(), tail.split()
            if len(hp) != 3 or not parts or not parts[0].isdigit():
                continue
            try:
                level, x, z = int(hp[0]), int(hp[1]), int(hp[2])
            except ValueError:
                continue
            yield mx * 64 + x, mz * 64 + z, level, int(parts[0])


def spawns(target_id, section="LOC", base=None):
    """Every (x, z, level) a loc or npc id appears at."""
    base = _content(base)
    return sorted(
        {(x, z, lvl) for x, z, lvl, rid in _rows(base, section) if rid == target_id}
    )


def _loc_rows(base, level=None):
    """Yield (x, z, lvl, id, shape, rotation) for LOC rows, keeping the geometry.

    `_rows` throws shape and rotation away, which is most of what a LOC row
    says. The full form is `level x z: id shape [rotation]`, and **rotation is
    omitted when it is 0** -- a two-field row is rotation 0, not a row with
    missing data.
    """
    mapdir = os.path.join(_content(base), "maps")
    for fn in os.listdir(mapdir):
        m = ROW.match(fn)
        if not m:
            continue
        mx, mz = int(m.group(1)), int(m.group(2))
        inside = False
        for line in io.open(os.path.join(mapdir, fn), errors="ignore"):
            if line.startswith("==== LOC"):
                inside = True
                continue
            if line.startswith("===="):
                if inside:
                    break
                continue
            if not inside or ":" not in line:
                continue
            head, tail = line.split(":", 1)
            hp, parts = head.split(), tail.split()
            if len(hp) != 3 or not parts or not parts[0].isdigit():
                continue
            lvl, lx, lz = (int(v) for v in hp)
            if level is not None and lvl != level:
                continue
            rid = int(parts[0])
            shape = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            rot = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            yield (mx * 64 + lx, mz * 64 + lz, lvl, rid, shape, rot)


# A wall sits on a tile EDGE, not on the tile. Rotation says which edge:
# 0 west, 1 north, 2 east, 3 south. This is the whole reason blocked() is wrong
# in both directions -- it marks the tile, so it forbids standing somewhere you
# can stand and permits walking through a wall from the far side.
_EDGE = {0: (-1, 0), 1: (0, 1), 2: (1, 0), 3: (0, -1)}

# Shapes that put a wall on one edge (0) or wrap a corner onto two (2).
WALL_STRAIGHT = 0
WALL_CORNER = 2
# Shapes that occupy the whole tile rather than an edge.
SOLID_SHAPES = (9, 10, 11)
# Ground decor and roofs never block a walker.
IGNORED_SHAPES = (12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22)


def wall_edges(x_lo, x_hi, z_lo, z_hi, level=0, base=None, passable=None):
    """Blocked transitions as a set of ((x,z),(nx,nz)) pairs, both directions.

    This is what indoor navigation needs and what `blocked()` cannot express.
    A character standing at (2618,3315) could not reach a ladder one tile west
    at (2617,3315): the LOC row on her own tile is `1602 0`, a timberwall of
    shape 0 rotation 0, which is a wall on her west edge. No tile-level model
    can say that -- both tiles are perfectly standable.

    Doors are excluded, because a door is a passage with a condition, not a
    wall. Pass `passable` to override the default name list.
    """
    passable = PASSABLE if passable is None else passable
    idname = names(_content(base), "loc.pack")
    out = set()
    for x, z, lvl, rid, shape, rot in _loc_rows(base, level):
        if not (x_lo <= x <= x_hi and z_lo <= z <= z_hi):
            continue
        if shape in IGNORED_SHAPES:
            continue
        if is_passable(rid, idname.get(rid, "loc_%d" % rid), passable):
            continue
        rots = ()
        if shape == WALL_STRAIGHT:
            rots = (rot,)
        elif shape == WALL_CORNER:
            rots = (rot, (rot + 1) % 4)
        else:
            continue
        for r in rots:
            dx, dz = _EDGE[r]
            a, b = (x, z), (x + dx, z + dz)
            out.add((a, b))
            out.add((b, a))
    return out


def solid_tiles(x_lo, x_hi, z_lo, z_hi, level=0, base=None, passable=None):
    """Tiles wholly occupied by a loc -- shapes 9, 10 and 11."""
    passable = PASSABLE if passable is None else passable
    idname = names(_content(base), "loc.pack")
    out = set()
    for x, z, lvl, rid, shape, rot in _loc_rows(base, level):
        if shape not in SOLID_SHAPES:
            continue
        if not (x_lo <= x <= x_hi and z_lo <= z <= z_hi):
            continue
        if is_passable(rid, idname.get(rid, "loc_%d" % rid), passable):
            continue
        out.add((x, z))
    return out


def band(x_lo, x_hi, z_lo, z_hi, section="LOC", level=None, base=None):
    """Every (x, z, id, name) in a rectangle. `level=0` for the surface."""
    base = _content(base)
    idname = names(base, "loc.pack" if section == "LOC" else "npc.pack")
    out = []
    for x, z, lvl, rid in _rows(base, section):
        if not (x_lo <= x <= x_hi and z_lo <= z <= z_hi):
            continue
        if level is not None and lvl != level:
            continue
        out.append((x, z, rid, idname.get(rid, f"loc_{rid}")))
    return sorted(set(out))


def distinct_names(x_lo, x_hi, z_lo, z_hi, section="LOC", level=None, base=None):
    """Counter of names in a rectangle. Read this before grepping for a word."""
    return Counter(r[3] for r in band(x_lo, x_hi, z_lo, z_hi, section, level, base))


_FLAG_CACHE = {}


def _square_flags(mx, mz, base=None):
    """(x,z) -> flag int for level 0 of one map square, cached.

    The MAP section rows read `level x z: h<height> f<flags> u<underlay>`. The
    f field is absent on most tiles, which is why it is easy to miss entirely.
    """
    key = (mx, mz, base or DEFAULT_CONTENT)
    if key in _FLAG_CACHE:
        return _FLAG_CACHE[key]
    path = os.path.join(_content(base), "maps", "m%d_%d.jm2" % (mx, mz))
    out = {}
    if os.path.exists(path):
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("===="):
                    if "LOC" in line:
                        break
                    continue
                head, sep, rest = line.partition(":")
                if not sep:
                    continue
                parts = head.split()
                if len(parts) != 3:
                    continue
                try:
                    lvl, lx, lz = (int(v) for v in parts)
                except ValueError:
                    continue
                if lvl != 0:
                    continue
                for tok in rest.split():
                    if tok.startswith("f") and tok[1:].isdigit():
                        out[(mx * 64 + lx, mz * 64 + lz)] = int(tok[1:])
                        break
    _FLAG_CACHE[key] = out
    return out


_OVERLAY_CACHE = {}


def _square_overlays(mx, mz, base=None):
    """(x,z) -> overlay id for level 0 of one map square, cached.

    MAP rows carry an `o` field as well as `h`, `f` and `u`, in the form
    `o<id>[;shape[;rotation]]`. Nothing here read it until 2026-09-13, which
    left a whole class of terrain invisible: a character stood on a riverbank
    with every eastward step refused and the flags said nothing, because the
    river is an overlay.
    """
    key = (mx, mz, base or DEFAULT_CONTENT)
    if key in _OVERLAY_CACHE:
        return _OVERLAY_CACHE[key]
    path = os.path.join(_content(base), "maps", "m%d_%d.jm2" % (mx, mz))
    out = {}
    if os.path.exists(path):
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("===="):
                    if "LOC" in line:
                        break
                    continue
                head, sep, rest = line.partition(":")
                if not sep:
                    continue
                parts = head.split()
                if len(parts) != 3:
                    continue
                try:
                    lvl, lx, lz = (int(v) for v in parts)
                except ValueError:
                    continue
                if lvl != 0:
                    continue
                for tok in rest.split():
                    if tok.startswith("o"):
                        oid = tok[1:].split(";")[0]
                        if oid.isdigit():
                            out[(mx * 64 + lx, mz * 64 + lz)] = int(oid)
                        break
    _OVERLAY_CACHE[key] = out
    return out


# Measured against 1033 tiles a character stood on and 480 it was refused:
#
#   overlay 19 : 0 walked, 57 refused   -- water, never passable
#   overlay  6 : 12 walked, 113 refused -- water edge, effectively impassable
#   overlay 10 : 158 walked, 5 refused  -- ROAD, the most-walked surface here
#   overlay  5 : 29 walked, 2 refused   -- walkable
BLOCKING_OVERLAYS = frozenset({6, 19})
ROAD_OVERLAY = 10


def overlay_map(x_lo, x_hi, z_lo, z_hi, base=None):
    out = {}
    for mx in range(x_lo // 64, x_hi // 64 + 1):
        for mz in range(z_lo // 64, z_hi // 64 + 1):
            for (x, z), o in _square_overlays(mx, mz, base).items():
                if x_lo <= x <= x_hi and z_lo <= z <= z_hi:
                    out[(x, z)] = o
    return out


def roads(x_lo, x_hi, z_lo, z_hi, base=None):
    """Tiles carrying the road overlay.

    The road network runs unbroken from x2560 to x3263 -- Ardougne past Varrock.
    A planner that prefers it walks ground the world was built to be walked on,
    instead of discovering riverbanks one refusal at a time.
    """
    return {
        t
        for t, o in overlay_map(x_lo, x_hi, z_lo, z_hi, base).items()
        if o == ROAD_OVERLAY
    }


BLOCKED_BIT = 1


def terrain_blocked(x_lo, x_hi, z_lo, z_hi, base=None):
    """Tiles the world's own terrain marks impassable -- water, lava, cliffs.

    This is the answer to the oldest complaint in this module, that the loc
    files cannot see terrain. They cannot; the MAP section can, and it was
    sitting in the same files the whole time.

    Validated against live ground truth before being trusted: of tiles a
    character was actually refused, 84.7% carry bit 1; of tiles a character
    actually stood on, 2.9% do. Nothing else correlated -- bits 2, 8 and 16
    never appeared on either set, and bit 4 appeared on walked tiles far more
    often than refused ones, so it is not a blocker.
    """
    out = set()
    for mx in range(x_lo // 64, x_hi // 64 + 1):
        for mz in range(z_lo // 64, z_hi // 64 + 1):
            for (x, z), fl in _square_flags(mx, mz, base).items():
                if fl & BLOCKED_BIT and x_lo <= x <= x_hi and z_lo <= z <= z_hi:
                    out.add((x, z))
    # Water is an overlay, not a flag. Without this a plan crosses rivers.
    for t, o in overlay_map(x_lo, x_hi, z_lo, z_hi, base).items():
        if o in BLOCKING_OVERLAYS:
            out.add(t)
    return out


# Names of things that stop a character. Matched as substrings, so "wall"
# catches brickwall and drystonewall.
#
# This list is load-bearing and was badly incomplete. It held only lava,
# railing, wall and fence, which misses `castlearrowslit` -- 364 of them in the
# Falador-to-Ardougne corridor alone -- plus `hedge` (245), `castlecrumbly`,
# `pileofbricks` and every ore rock. The failure is silent and specific: a
# planner sees a doorway where a castle wall is, routes through it, and the
# character is refused at a tile the map swears is open.
#
# Caught live: a scout planning west out of Falador was routed through the city
# wall at (2935,3354-3356), where the loc is `castlecrumbly` and `pileofbricks_r`
# rather than `castlewall`. Three tiles of missing keyword sealed a 321-tile
# route the moment the live refusals were learned.
#
# Note this is wrong in BOTH directions and always has been: a wall loc sits on
# a tile edge, so the tile itself is often still walkable. Checked against 847
# tiles a live character actually stood on, the pre-existing "wall" keyword
# alone accounts for 53 such false positives. Over-reporting is the safer of
# the two errors -- it routes around a wall you could have hugged, rather than
# through one you cannot pass -- but it is the reason this is a heuristic and
# not a walkability map. "brick" was deliberately NOT added: bricks_1/bricks_2
# are ground decoration, and brickwall is already caught by "wall".
BLOCKING = (
    "lava",
    "railing",
    "wall",
    "fence",
    "castle",
    "hedge",
    "crumbl",
    "pileof",
    "rubble",
    "boulder",
    "rock",
)

# Things a character goes *through*, which must never be recorded as blocking
# even when they match the list above -- `inaccastledoubledoorropen` matches
# "castle" and is a door. A requirement-gated passage is not a wall.
PASSABLE = ("door", "gate", "stile", "ladder", "stair", "arch", "rocking")

# Passages that are NAMELESS in loc.pack, so the name check above cannot see
# them. This list is not a nicety: treating one of these as a wall is how two
# characters decided the Falador/Taverley boundary was the edge of the world,
# and how a planner later called the Ardougne Castle chest room "sealed" when
# its door is `loc_2556`, a Thieving 13 lock.
#
# 2550-2559 are the locked doors from scripts/skill_thieving; 1596/1597 are the
# fence gates. All of them open, some want a level or a lockpick -- and a
# requirement-gated passage is never a wall.
PASSABLE_IDS = frozenset({1596, 1597, 2550, 2551, 2554, 2555, 2556, 2557, 2558, 2559})


def is_passable(rid, name, passable=PASSABLE):
    """True if a loc is something a character goes through rather than around."""
    low = (name or "").lower()
    return rid in PASSABLE_IDS or any(p in low for p in passable)


def blocked(x_lo, x_hi, z_lo, z_hi, base=None, keywords=BLOCKING, passable=PASSABLE):
    """Tiles carrying a loc that certainly blocks. NOT a walkability map.

    Still one-directional: it reports what is known to block, never that a tile
    is walkable. Terrain -- water, lava ground, unmapped rock -- carries no loc
    at all, so it cannot appear here. That is why `maze.py`'s learned set exists.
    """
    locs = {
        (x, z)
        for x, z, rid, nm in band(x_lo, x_hi, z_lo, z_hi, "LOC", 0, base)
        if any(k in nm.lower() for k in keywords)
        and not any(p in nm.lower() for p in passable)
    }
    return locs | terrain_blocked(x_lo, x_hi, z_lo, z_hi, base)


def _cli():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--content", default=None, help="path to the Content clone")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("spawns", help="where does an id appear")
    sp.add_argument("id", type=int)
    sp.add_argument("--section", default="LOC", choices=["LOC", "NPC"])

    bd = sub.add_parser("band", help="what is in a rectangle")
    for f in ("x_lo", "x_hi", "z_lo", "z_hi"):
        bd.add_argument(f, type=int)
    bd.add_argument("--section", default="LOC", choices=["LOC", "NPC"])
    bd.add_argument("--level", type=int, default=0)
    bd.add_argument(
        "--names-only", action="store_true", help="just the distinct names and counts"
    )

    a = ap.parse_args()
    if a.cmd == "spawns":
        rows = spawns(a.id, a.section, a.content)
        print(json.dumps({"id": a.id, "section": a.section, "count": len(rows)}))
        for x, z, lvl in rows:
            print(json.dumps({"x": x, "z": z, "level": lvl, "wilderness": z > 3520}))
    else:
        if a.names_only:
            for nm, n in distinct_names(
                a.x_lo, a.x_hi, a.z_lo, a.z_hi, a.section, a.level, a.content
            ).most_common():
                print(json.dumps({"name": nm, "count": n}))
        else:
            for x, z, rid, nm in band(
                a.x_lo, a.x_hi, a.z_lo, a.z_hi, a.section, a.level, a.content
            ):
                print(json.dumps({"x": x, "z": z, "id": rid, "name": nm}))


if __name__ == "__main__":
    _cli()
