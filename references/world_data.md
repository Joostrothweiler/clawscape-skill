# Reading the world's own data

This world runs LostCityRS content at branch `225`. That content is public, so
a question like "where do zombies spawn" or "what drops a nature rune" has an
exact answer sitting in a file, and does not need to be explored for.

    git clone --depth 1 --branch 225 https://github.com/LostCityRS/Content.git

It is about 119 MB shallow. Treat it as a lookup table, not as truth about the
live world: it says what the world was built from, and a live check still
decides whether something is actually standing there right now.

## The map files are plain text

`maps/*.jm2` are ASCII, not binary. An earlier session recorded the opposite
and went hunting for monsters by walking corridors for a whole session as a
result. Each file covers one 64x64 square, named `m<mapX>_<mapZ>.jm2`, and has
three sections:

    ==== MAP ====
    ==== LOC ====
    ==== NPC ====

Rows in the LOC and NPC sections read **`level x z: id [angle]`**, where `x`
and `z` are local to the square. World coordinates are therefore:

    worldX = mapX * 64 + x
    worldZ = mapZ * 64 + z

Watch the field order. `0 0 0`, `0 0 1`, `0 0 2` is one loc repeated along z
at level 0, not three levels of the same tile. Reading it as `x z level`
produces coordinates that look plausible and are wrong.

Ids come from `pack/loc.pack` and `pack/npc.pack`, one `id=name` per line.

## Finding every spawn of something

```python
import os, re


def spawns(locid, section="NPC", mapdir="maps"):
    hits = []
    for fn in os.listdir(mapdir):
        m = re.match(r"m(\d+)_(\d+)\.jm2", fn)
        if not m:
            continue
        mx, mz = int(m.group(1)), int(m.group(2))
        inside = False
        for line in open(os.path.join(mapdir, fn), errors="ignore"):
            if line.startswith("==== " + section):
                inside = True
                continue
            if line.startswith("===="):
                inside = False
                continue
            if not inside or ":" not in line:
                continue
            head, tail = line.split(":", 1)
            parts = tail.split()
            if parts and parts[0] == str(locid):
                lvl, x, z = head.split()
                hits.append((mx * 64 + int(x), mz * 64 + int(z), int(lvl)))
    return sorted(hits)
```

## Drop tables

`scripts/drop tables/scripts/<monster>.rs2`, one file per monster, each a
straight `random(128)` ladder:

    def_int $dropint = random(128);
    if ($dropint < 34) { ... } else if ($dropint < 35) {
        obj_add(npc_coord, naturerune, 6, ^lootdrop_duration);
    }

So a band's width over 128 is the drop rate, and the number after the item is
the stack size. Read the whole ladder rather than grepping one line: the same
file often holds several variants (`unarmed_zombie`, `armed_zombie`) with very
different tables, and which one a given NPC uses is the `[ai_queue3,<name>]`
line at the top.

## Worked example: the nature rune problem

Nature runes are the block on alchemy, and no F2P shop in this world stocks
them. What the data actually says:

| Source | Rate | Stack | Reachable? |
| --- | --- | --- | --- |
| `zombie2` / unarmed zombie | 1/128 | **6** | yes, Varrock sewers |
| Guard | 1/128 | 1 | yes, Varrock palace yard |
| Thieving chest (`chest_nature_rune`) | every open, 30-tick respawn | 1 | **no**: two in members' Ardougne, one at (3042, 3949), deep Wilderness |

The thieving chest needs Thieving 28 and pays 250 xp an open, which would be
the best source by a wide margin if any of the three sat in reachable F2P
ground. None do.

`zombie2` spawns ten deep around (3139-3151, 9883-9907) in the Varrock sewers.
The two lone `zombie_unarmed` spawns at (3243, 9893) and (3259, 9891) are much
closer to the manhole ladder and confirmed live, but two spawns will not keep
a kill loop fed. The route west to the cluster is still unsolved: `travel.py`
narrowed its hop to 3 and still could not get out of the corridor.

## What this data is not good for

**Terrain overlays are not a walkability signal.** The `MAP` section's `o`
token looked like it should mark water, and `o6` is `gungywater` in
`pack/flo.pack`. Blocking on it marked **21 of 175 tiles a character had
actually stood on** as impassable, including the floor of Lowe's Archery
Emporium. An offline model built on it concluded the whole west bank of the
river was unreachable without entering the Wilderness, which is simply false.
Loc-derived collision validated at about 97% against the same real tiles;
overlays did not validate at all. Use locs, ignore overlays.

**Do not use this data to prove something is impossible.** Built from locs
alone it still over-blocks interactable tiles, since a ladder, a manhole and a
shop counter are locs you walk onto, and it treats unmapped rock as open
floor, so a region can leak. In one dungeon band that produced 278 components,
239 of them under 10 tiles. It is a tool for *finding* a route and for knowing
what exists where. A negative result from it is a hypothesis to test in game,
not an answer.

**The server is the authority on reachability, and it is free to ask.** Every
row in `state npcs` and `state locs` carries `reachable`, computed by the
server's own pathfinder. One `walkTo` at a reachable destination does better
pathfinding than any of this, and the worked example below is a case where it
beat the model outright.

## Worked example: two dungeons that look like one

The Varrock sewers and the western section holding the `zombie2` cluster are
**not connected**, and a session was spent walking a corridor west that does
not go anywhere. What the map data shows is two separate components with
roughly 80 tiles of solid wall between them, and what the world confirms is
that the western one is the Edgeville dungeon with its own entrance:

| | |
| --- | --- |
| Varrock sewers | Manhole (3237, 3458), ladder down to (3237, 9859) |
| Edgeville dungeon | **Trapdoor (3097, 3468)**, Open then Climb-down, lands at (3096, 9868) |

The trapdoor sits in the Edgeville graveyard, west of the river, beside a
coffin. Getting to it from Varrock means crossing the river, which one
`walkTo` at a reachable tile does by itself.

Underground, that dungeon is itself split into pockets that do not connect at
floor level: skeletons and giant spiders near the ladder, giant rats east
along z 9882, and hobgoblins walled off to the north. Nature runes are in all
three, so pick the pocket you can stand in rather than the best table:

| Monster | Rate | Stack | Per kill |
| --- | --- | --- | --- |
| Hobgoblin | 2/128 | 4 | 0.063 |
| Unarmed zombie | 1/128 | 6 | 0.047 |
| Skeleton | 1/128 | 3 | 0.023 |
| Guard | 1/128 | 1 | 0.008 |
