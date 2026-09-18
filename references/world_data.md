# Reading the world's own data

This world runs LostCityRS content at branch `225`. That content is public, so
a question like "where do zombies spawn" or "what drops a nature rune" has an
exact answer sitting in a file, and does not need to be explored for.

    git clone --depth 1 --branch 225 https://github.com/LostCityRS/Content.git

It is about 119 MB shallow. Treat it as a lookup table, not as truth about the
live world: it says what the world was built from, and a live check still
decides whether something is actually standing there right now.

## Skill xp is 2.5x the content pack, on every skill measured

**Multiply every `experience` or `*_exp` value in the pack by 2.5 to get what
this world actually awards.** Measured live on 2026-09-18 across three
unrelated skills, each confirmed against the pack's own number:

| Action | Pack says | This world gives | Ratio |
| --- | --- | --- | --- |
| High alchemy (`magic_spells.dbrow`, `experience,650`) | 650 | **1,625** | 2.5 |
| Burying big bones (`bone_exp=150`) | 150 | **375** | 2.5 |
| Feathering 15 arrow shafts (`multiply($arrow_count, 10)`) | 150 | **375** | 2.5 |

The Fletching one was sampled ten times in a row without variation. Three
skills, three subsystems -- a spell, an item interaction and an inventory
combine -- so this is a world-wide rate, not a per-skill tweak.

**Why it matters more than it looks.** It makes the pack's xp numbers *usable*.
Before this, every plan built on config xp was silently 60% pessimistic, and
the natural response to a disappointing estimate is to drop the goal. Fletching
was nearly dropped that way: the pack's numbers made levelling it look like
hundreds of logs, and the measured rate took **Fletching 1 to 22 in eighteen
seconds** for 150 bought shafts and 150 feathers, about 450 coins.

**This is separate from the level table, which is flatter here than the
original game's.** Level 99 in this world is about **1,005,000 xp** rather than
13,034,431. So a goal's cost has two corrections: multiply the pack's rate by
2.5, and do not reuse any level-to-xp table from outside.

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

## Dargaud's Bow and Arrows, and a claim it overturns

The Ranging Guild's arrow shop at **(2673,3433)** — `ranging_guild_bow_salesman`,
npc 683, inside the guild door `loc_2514` at **(2658,3438)** — stocks, read
live on 2026-09-18:

| Line | Stock | Listed price |
| --- | --- | --- |
| **Arrow shaft** | 1,000 | **1** |
| Bronze / Iron / Steel arrowtips | 500 / 400 / 300 | 1 / 2 / 6 |
| Mithril / Adamant / Rune arrowtips | 200 / 200 / 150 | 16 / 40 / 200 |
| Bronze / Iron / Steel arrow | 1,000 / 500 / 500 | 1 / 3 / 12 |
| **Mithril / Adamant / Rune arrow** | **500 / 450 / 400** | 32 / 80 / 400 |
| Shortbows and longbows to willow | 20 each | 50 to 320 |

**This repo has recorded that "every arrow above iron exists only as an
arrowhead, so better ammunition is a Fletching project, not a purchase, at any
shop in the world."** That was generalised from Catherby's archery shop, where
the finished-arrow lines really do sit at zero. It is wrong. Finished arrows
to **rune** are on this shelf, and so are arrow shafts, which means the
shaft→headless→arrow chain can run without ever owning a knife.

Two lessons, and the second is the one worth carrying:

- **A shop's stock list is a fact about that shop.** Two archery shops a few
  hundred tiles apart carry different lines, and reasoning from one to "any
  shop in the world" turned a local observation into a world model that sent
  a character on a 160-tile walk for a knife it did not need.
- **The listed price is a floor and it climbs steeply.** 130 mithril arrows
  cost 6,762 coins against a 32 gp listing — an effective **52 gp each**.
  Budget from the coin delta, buy in batches, and stop when the effective
  price stops being worth it.

Entry is `stat(ranged) < 40` at the door, and the door only admits from the
**west or north**: `ranging_guild_door.rs2` sends anyone standing east of it
or south of it straight back out. It is also **nameless in the loc data**
(`loc_2514`), so searching for "door" or "gate" in the band finds nothing.
