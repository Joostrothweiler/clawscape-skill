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
    locs, so "no wall in the data" does NOT mean walkable. The useful asymmetry
    is that *absence of a gate* is meaningful (there is nothing to open) while
    absence of a wall is not.
  - **Many locs have no name.** The Wilderness fence gates are `loc_1596` /
    `loc_1597` with no entry in `loc.pack`, so grepping for "gate" finds
    nothing and invites the conclusion that no opening exists. Use
    `distinct_names()` and read the list rather than searching for the word you
    expect.
"""

import argparse
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


def blocked(
    x_lo, x_hi, z_lo, z_hi, base=None, keywords=("lava", "railing", "wall", "fence")
):
    """Tiles carrying a loc that certainly blocks. NOT a walkability map."""
    return {
        (x, z)
        for x, z, rid, nm in band(x_lo, x_hi, z_lo, z_hi, "LOC", 0, base)
        if any(k in nm.lower() for k in keywords)
    }


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
