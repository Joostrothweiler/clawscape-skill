#!/usr/bin/env python3
"""Shared, growing knowledge of the world: tiles, objects, crossings, gaps.

`routes.json` is a travel log -- a record of journeys. This is the map those
journeys add up to, plus a dictionary of what things are. The point is that it
**compounds**: every session should start knowing more than the last one did,
without anybody deciding to write something down.

How the loop works:

    play  ->  observe()  ->  observations.jsonl  ->  fold  ->  atlas.json
                  ^                                              |
                  +---------------- brief / frontier ------------+

  - **observe()** is passive. `walk.py` and `maze.py` call it on every settled
    state read, so merely moving around records which tiles were stood on and
    every loc and npc that came into view, with its id, options and coordinates.
    Nothing is learned "on purpose".
  - **fold** merges the local log into the shared atlas under a lock, then
    truncates the log. Counts accumulate, so confidence grows with evidence.
  - **brief** and **frontier** are what make it a loop rather than an archive:
    they say what is known and, more usefully, where the edges of knowledge are,
    so the next session can be pointed at a gap instead of rediscovering ground.

Two rules the schema exists to enforce, both learned by getting them wrong:

  - **A refusal is not always a wall.** A tile can refuse because of terrain, or
    because a gate needs opening, or because the character lacks a level or an
    item. Recording the Pirates' Hideout door as "blocked" would tell every
    future agent it is impassable when it needs Thieving 39 and a lockpick. So
    tiles carry a `reason`, and requirement-gated passages are `crossings` with
    a `requires`, never blockers.
  - **One failure is not evidence.** A monster standing on a tile refuses it
    once. Blocks need repeated independent failures before they are believed,
    and a tile that later proves walkable clears its block outright.

Objects are keyed by **id**, not name, because many locs have no name at all:
the Wilderness fence gates are 1596/1597 with no entry in `loc.pack`, which is
why searching for "gate" found nothing and cost a day. An alias recorded here is
how the next agent finds them.
"""

import argparse
import atexit
import fcntl
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ATLAS = os.path.join(HERE, "atlas.json")
OBSERVATIONS = os.path.join(HERE, "observations.jsonl")

# How many independent refusals before a tile is believed impassable, and how
# many sightings before an object's option list is treated as settled.
BLOCK_CONFIDENCE = 2

EMPTY = {
    "version": 1,
    "tiles": {},  # "x,z" -> {"walk": n, "block": n, "reason": str|None}
    "objects": {},  # "id" -> {alias, kind, options, names, seen, samples, note}
    "crossings": {},  # "id" -> {verb, requires, note}
    "notes": {},
}


def _load(path=ATLAS):
    try:
        with open(path) as fh:
            d = json.load(fh)
    except Exception:
        return json.loads(json.dumps(EMPTY))
    for k, v in EMPTY.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    return d


def _update(mutate, path=ATLAS):
    """Apply mutate(atlas) under a lock spanning load and save.

    The same discipline travel.py uses for routes.json: this file is written by
    every character playing at once, and a writer that loads early and saves late
    silently drops whatever anyone else added in between.
    """
    lock = path + ".lock"
    with open(lock, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            atlas = _load(path)
            mutate(atlas)
            tmp = path + ".tmp"
            with open(tmp, "w") as out:
                json.dump(atlas, out, indent=2, sort_keys=True)
            os.replace(tmp, path)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return atlas


def tile_key(x, z):
    return f"{x},{z}"


_autofold_armed = False


def _autofold():
    """Fold whatever this process observed, however it exits.

    Folding used to be a step someone had to remember at the end of a session,
    which meant a crash, a timeout or a distracted operator threw the session's
    map away. Any process that observes now folds its own observations on exit,
    so the only way to lose them is for the machine to die outright.
    """
    try:
        fold()
    except Exception:
        pass


# ---------------------------------------------------------------- observing


def observe(state, stood=None, refused=None, reason=None, path=OBSERVATIONS):
    """Append what a live state read shows. Cheap, lossy, called constantly.

    `stood` is the tile the character is actually on; `refused` a tile it tried
    and failed to reach. Neither is required -- just passing a state dict still
    records every object in view.
    """
    if not state:
        return
    rec = {"locs": [], "npcs": []}
    p = state.get("player") or {}
    if stood is None and "worldX" in p:
        stood = [p["worldX"], p["worldZ"]]
    if stood:
        rec["stood"] = list(stood)
    if refused:
        rec["refused"] = list(refused)
        rec["reason"] = reason

    for loc in state.get("nearbyLocs") or []:
        rec["locs"].append(
            {
                "id": loc.get("id"),
                "name": loc.get("name"),
                "x": loc.get("x"),
                "z": loc.get("z"),
                "options": [o.get("text") for o in loc.get("optionsWithIndex") or []],
            }
        )
    for npc in state.get("nearbyNpcs") or []:
        rec["npcs"].append(
            {
                "id": npc.get("id"),
                "name": npc.get("name"),
                "x": npc.get("x"),
                "z": npc.get("z"),
                "level": npc.get("combatLevel"),
            }
        )
    if not (rec.get("stood") or rec.get("refused") or rec["locs"] or rec["npcs"]):
        return
    global _autofold_armed
    if not _autofold_armed:
        atexit.register(_autofold)
        _autofold_armed = True
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except Exception:
        pass  # observation must never break play


# ------------------------------------------------------------------ folding


def fold(obs_path=OBSERVATIONS, atlas_path=ATLAS, keep_log=False):
    """Merge the local observation log into the shared atlas, then clear it."""
    if not os.path.isfile(obs_path):
        return {"folded": 0}
    rows = []
    with open(obs_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    if not rows:
        return {"folded": 0}

    stats = Counter()

    def mutate(atlas):
        tiles, objects = atlas["tiles"], atlas["objects"]
        for rec in rows:
            if rec.get("stood"):
                k = tile_key(*rec["stood"])
                t = tiles.setdefault(k, {"walk": 0, "block": 0, "reason": None})
                t["walk"] += 1
                # standing on a tile disproves any earlier block outright
                if t["block"]:
                    t["block"] = 0
                    t["reason"] = None
                    stats["blocks_cleared"] += 1
                stats["tiles_walked"] += 1
            if rec.get("refused"):
                k = tile_key(*rec["refused"])
                t = tiles.setdefault(k, {"walk": 0, "block": 0, "reason": None})
                if not t["walk"]:  # never contradict direct evidence
                    t["block"] += 1
                    t["reason"] = rec.get("reason") or t.get("reason")
                    stats["tiles_refused"] += 1
            for loc in rec.get("locs") or []:
                if loc.get("id") is None:
                    continue
                o = objects.setdefault(
                    str(loc["id"]),
                    {
                        "alias": None,
                        "kind": None,
                        "options": [],
                        "names": [],
                        "seen": 0,
                        "samples": [],
                        "note": None,
                    },
                )
                o["seen"] += 1
                nm = loc.get("name")
                if nm and nm not in o["names"]:
                    o["names"].append(nm)
                for opt in loc.get("options") or []:
                    if opt and opt not in o["options"]:
                        o["options"].append(opt)
                        stats["options_learned"] += 1
                sample = [loc.get("x"), loc.get("z")]
                if None not in sample and sample not in o["samples"]:
                    if len(o["samples"]) < 8:
                        o["samples"].append(sample)
                stats["locs_seen"] += 1
            for npc in rec.get("npcs") or []:
                if npc.get("id") is None:
                    continue
                o = objects.setdefault(
                    f"npc:{npc['id']}",
                    {
                        "alias": None,
                        "kind": "npc",
                        "options": [],
                        "names": [],
                        "seen": 0,
                        "samples": [],
                        "note": None,
                    },
                )
                o["seen"] += 1
                nm = npc.get("name")
                if nm and nm not in o["names"]:
                    o["names"].append(nm)
                if npc.get("level") is not None:
                    o["level"] = npc["level"]
                sample = [npc.get("x"), npc.get("z")]
                if None not in sample and len(o["samples"]) < 8:
                    if sample not in o["samples"]:
                        o["samples"].append(sample)
                stats["npcs_seen"] += 1

    _update(mutate, atlas_path)
    if not keep_log:
        open(obs_path, "w").close()
    out = {"folded": len(rows)}
    out.update(stats)
    return out


# ------------------------------------------------------------------ reading


def walkable(atlas=None):
    atlas = atlas or _load()
    return {k for k, v in atlas["tiles"].items() if v.get("walk")}


def blocked(atlas=None, confidence=BLOCK_CONFIDENCE):
    """Tiles believed impassable. Requirement-gated passages are NOT here."""
    atlas = atlas or _load()
    return {
        k
        for k, v in atlas["tiles"].items()
        if not v.get("walk") and v.get("block", 0) >= confidence
    }


def frontier(atlas=None, limit=40):
    """Walkable tiles with an unknown neighbour: where the map runs out.

    This is the whole point of recording coverage. It turns "explore" from a
    vague instruction into a list of specific tiles worth standing next to.
    """
    atlas = atlas or _load()
    known = set(atlas["tiles"])
    walk = walkable(atlas)
    edges = []
    for k in walk:
        x, z = (int(v) for v in k.split(","))
        unknown = [
            (x + dx, z + dz)
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if tile_key(x + dx, z + dz) not in known
        ]
        if unknown:
            edges.append((len(unknown), [x, z], [list(u) for u in unknown]))
    edges.sort(reverse=True)
    return [{"tile": t, "unknown_neighbours": u} for _, t, u in edges[:limit]]


def coverage(atlas=None):
    atlas = atlas or _load()
    squares = defaultdict(lambda: {"walkable": 0, "blocked": 0})
    for k, v in atlas["tiles"].items():
        x, z = (int(n) for n in k.split(","))
        sq = f"{x // 64}_{z // 64}"
        if v.get("walk"):
            squares[sq]["walkable"] += 1
        elif v.get("block", 0) >= BLOCK_CONFIDENCE:
            squares[sq]["blocked"] += 1
    return dict(squares)


def unnamed(atlas=None, min_seen=1):
    """Objects seen live that still have no alias. The dictionary's to-do list."""
    atlas = atlas or _load()
    out = []
    for oid, o in atlas["objects"].items():
        if o.get("alias"):
            continue
        if o.get("seen", 0) < min_seen:
            continue
        if o.get("names"):
            continue  # the world names it; an alias adds little
        out.append(
            {
                "id": oid,
                "seen": o["seen"],
                "options": o.get("options", []),
                "samples": o.get("samples", [])[:3],
            }
        )
    out.sort(key=lambda r: -r["seen"])
    return out


def _stranded(path=OBSERVATIONS):
    """Observations written but never folded. Should always be 0."""
    try:
        with open(path) as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def _close():
    """One command for the end of a session, so there are not four to forget."""
    folded = fold()
    atlas = _load()
    todo = unnamed(atlas)
    edge = frontier(atlas, limit=3)
    print(
        json.dumps(
            {
                "folded": folded,
                "tiles_known": len(atlas["tiles"]),
                "objects_known": len(atlas["objects"]),
                "needs_naming": todo[:10],
                "next_frontier": edge,
                "now_commit": [
                    "git add recipes/atlas.json recipes/routes.json",
                    "git commit -m 'recipes: <what this session learned>'",
                    "merge upstream/main first; both files are shared, so merge, "
                    "never overwrite, and check the result is additive",
                ],
                "reminder": "name anything in needs_naming before committing -- an "
                "unnamed object is one the next agent works out from scratch",
            },
            indent=2,
        )
    )
    return 0


# -------------------------------------------------------------------- CLI


def _cli(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fold", help="merge the observation log into the atlas")
    sub.add_parser(
        "close",
        help="end-of-session: fold, list what needs naming, "
        "show the frontier, print what to commit",
    )
    sub.add_parser("brief", help="what is known, and where the gaps are")
    sub.add_parser("coverage", help="tiles known per map square")

    fr = sub.add_parser("frontier", help="walkable tiles with unknown neighbours")
    fr.add_argument("--limit", type=int, default=20)

    un = sub.add_parser("unnamed", help="objects seen live with no alias yet")
    un.add_argument("--min-seen", type=int, default=1)

    nm = sub.add_parser("name", help="give an object an alias")
    nm.add_argument("id")
    nm.add_argument("--alias", required=True)
    nm.add_argument("--kind", default=None)
    nm.add_argument("--note", default=None)

    cr = sub.add_parser("crossing", help="record how a barrier is passed")
    cr.add_argument("id")
    cr.add_argument("--verb", required=True, help="Open, Cross, Slash, Push ...")
    cr.add_argument(
        "--requires", default=None, help="e.g. 'Thieving 39 + lockpick'; NOT a blocker"
    )
    cr.add_argument("--note", default=None)

    de = sub.add_parser("describe", help="what is known about an object")
    de.add_argument("id")

    a = ap.parse_args(argv)

    if a.cmd == "fold":
        print(json.dumps(fold(), indent=2))
        return 0
    if a.cmd == "coverage":
        print(json.dumps(coverage(), indent=2, sort_keys=True))
        return 0
    if a.cmd == "frontier":
        print(json.dumps(frontier(limit=a.limit), indent=2))
        return 0
    if a.cmd == "unnamed":
        print(json.dumps(unnamed(min_seen=a.min_seen), indent=2))
        return 0
    if a.cmd == "describe":
        atlas = _load()
        print(
            json.dumps(
                atlas["objects"].get(a.id)
                or atlas["objects"].get(f"npc:{a.id}")
                or {"unknown": a.id},
                indent=2,
            )
        )
        return 0
    if a.cmd == "name":

        def mut(atlas):
            o = atlas["objects"].setdefault(
                a.id,
                {
                    "alias": None,
                    "kind": None,
                    "options": [],
                    "names": [],
                    "seen": 0,
                    "samples": [],
                    "note": None,
                },
            )
            o["alias"] = a.alias
            if a.kind:
                o["kind"] = a.kind
            if a.note:
                o["note"] = a.note

        _update(mut)
        print(json.dumps({"named": a.id, "alias": a.alias}))
        return 0
    if a.cmd == "crossing":

        def mut(atlas):
            c = atlas["crossings"].setdefault(a.id, {})
            c["verb"] = a.verb
            if a.requires:
                c["requires"] = a.requires
            if a.note:
                c["note"] = a.note

        _update(mut)
        print(json.dumps({"crossing": a.id, "verb": a.verb}))
        return 0

    if a.cmd == "close":
        return _close()

    # brief
    atlas = _load()
    w, b = walkable(atlas), blocked(atlas)
    cov = coverage(atlas)
    verbs = sorted({c["verb"] for c in atlas["crossings"].values() if c.get("verb")})
    print(
        json.dumps(
            {
                "tiles_known": len(atlas["tiles"]),
                "walkable": len(w),
                "believed_blocked": len(b),
                "map_squares_touched": len(cov),
                "objects_known": len(atlas["objects"]),
                "objects_unnamed": len(unnamed(atlas)),
                "crossing_verbs": verbs,
                "frontier_sample": frontier(atlas, limit=5),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
