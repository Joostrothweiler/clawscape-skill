# Thieving

Nobody had trained Thieving in this world before 2026-09-12, so none of this
was written down. Every number below is read from the world's own config under
`scripts/skill_thieving/`, and the pickpocket rate is confirmed live.

## Pickpocketing

`interactNpc` with the NPC's own **Pickpocket** option. On Man and Woman that
option is **opIndex 3**, but read it from `optionsWithIndex` rather than
hard-coding it. `recipes/train.py --skill Thieving --npc Man --option
Pickpocket` drives it correctly, including the stun.

A failure stuns you for **13 ticks** and deals **2 damage**, so a long grind
drifts HP down slowly rather than threatening you. XP is a flat amount per
**success**; the level only improves how often you succeed.

**Read the multiplier note below before using these numbers.** The config
value is what `pickpocket.dbrow` stores; the live column is what the skill
actually awards.

| Target | Thieving | Config XP | **Live XP** | Notable loot |
| --- | --- | --- | --- | --- |
| Man / Woman | 1 | 80 | **200** | coins 3 |
| Farmer | 10 | 145 | **362** | |
| Warrior (`warrior_woman`, `al_kharid_warrior`) | 25 | 260 | **650** | coins 18 |
| Rogue | 32 | 365 | **912** | coins 25-40, 8 air runes, **lockpick**, iron dagger(p) |
| Guard (`guard1`, `guard2`, `ardougne_guard`) | 40 | 468 | **1170** | coins 30 |
| Knight of Ardougne | 55 | 843 | **2107** | |
| Watchman | 65 | 1375 | **3437** | |
| Paladin | 70 | 1518 | **3795** | |
| Gnome | 75 | 1983 | **4957** | |
| **Hero** | **80** | **2733** | **6832** | |

## The world awards 2.5x the config value

Measured twice, independently, on 2026-09-13:

| Target | Config | Live | Ratio |
| --- | --- | --- | --- |
| Man | 80 | 200 | 2.5 |
| Guard | 468 | 1170 | 2.5 |

An earlier version of this page listed Man at 200 and Guard at 468 in the same
column, which is the live figure for one and the config figure for the other.
That mix made Man look 2.5x better than it is relative to Guard, and it hid the
multiplier entirely. **Always state which column a number came from.**

Practically: a level goal costs 2.5x less xp than the config table suggests, so
compute grind estimates from the live column.

## Guards are not the best target, only the best one near Edgeville

This matters more than anything else on this page. Everything above Guard in
the table was missing from it, so an agent reading it would grind guards to 99
believing that was optimal. **A Hero pays 6832 live against a Guard's 1170 --
5.8x.**

The catch is where they stand. Every target above Guard is in Ardougne or the
Gnome Stronghold:

| Target | Nearest spawns | Region |
| --- | --- | --- |
| Hero (id 21, 3 spawns) | (2667,3316) (2647,3306) (2630,3288) | Ardougne |
| Paladin (id 20, 22 spawns) | (2653,3315) (2657,3307) | Ardougne |
| Knight of Ardougne (id 23, 5 spawns) | (2671,3313) (2652,3318) | Ardougne |
| Gnome (id 66, 44 spawns) | (2478,3502) (2482,3498) | Gnome Stronghold |
| Guard (id 9, 43 spawns) | (3093,3518) (3085,3518) (3109,3513) | **Edgeville, ~620 tiles closer** |

So the decision is a travel cost, not an xp comparison. The Edgeville guards were
measured live at roughly **800 xp per train.py round at ~7 ticks a round**, which
carries a character from 88 to 99 in well under an hour. A 620-tile trek through
unmapped ground to reach Heroes does not pay for itself over that distance --
but it pays enormously for any longer goal, and Ardougne is the gate on the
nature runes as well (below).

**The map squares for that corridor all exist:** m40_51 through m48_55 form an
unbroken chain from Falador to Ardougne, so the ground between them is real
world, not a gap. Whether it is walkable end to end is recorded in
`routes.json` as it gets tested.

Confirmed live on Man: 200 xp a success, and Thieving 1 to 28 took about 60
rounds in total.

**The Rogue is the only source of a lockpick found anywhere.** Its loot weights
are coins 108, air rune 8, jug of wine 6, **lockpick 5**, iron dagger(p) 1, out
of 128 — so roughly **3.9% per success**. That matters because a lockpick is
the gate on the best chests (below).

**Where they stand.** Warriors are the useful safe tap: `warrior_woman` at
**(3202, 3487)** and **(3205, 3487)** in Varrock, more around
(2569-2575, 3383-3388) and (2584-2632, 3289-3299); `al_kharid_warrior` at
(3282-3301, 3168-3177) in the Al Kharid palace. **All 22 Rogue spawns are in
the Wilderness**: two at (3076, 3916) and (3079, 3909), the rest at Rogues'
Castle (3276-3287, 3927-3939). So a lockpick costs a Wilderness trip.

## Grinding guards at Edgeville, and the trap in the bank run

The guards stand at **(3093,3518), (3085,3518), (3109,3513), (3110,3515),
(3114,3512), (3114,3517)**, at **Edgeville** -- not Falador, which is 240 tiles
south-west at (3015,3354). The bank booth is **(3095,3489, loc 2213)**, about 28
tiles south of the guards, and `routes.json` records the spot as
`edgeville_bank` (3096,3492). That is a short, self-funding loop: pickpocket,
bank the coins, restock lobsters, walk back.

**Check the landmark before naming a town.** These guards were written up as
Falador's for most of a session. Every coordinate was right and the name was
wrong, which is the kind of error that survives review and sends the next agent
240 tiles to the wrong place. `routes.json` landmarks answer it in one lookup.

**The trap:** the straight line between booth and guards runs through the bank
building's `brickwall`. A waypoint walk from the booth north along x3094 is
refused at about z3506, and the only openings nearby are `openbankdoor_l`
(3101,3509) and `openthickpoordoor` (3101,3510) -- east of that line. `maze.py`
routes around it correctly; a straight `walk.py` waypoint chain does not.

**Why that is worth a section:** a loop that walked the straight line left a
character standing at (3094,3500) and then ran `train.py` against a Guard that
was 18 tiles away and out of range. `train.py` reported `"dispatched": true`
every single round. Thirty-plus rounds produced zero xp while every log line
looked like success.

**So: never judge a training loop by whether it dispatched. Judge it by whether
xp moved.** A round that gains nothing is the only trustworthy signal that the
character is not where the loop believes it is. Compare experience before and
after each round, and on two flat rounds reposition with `maze.py` rather than
continuing. `nearbyNpcs` is the state field that says whether a target is
actually in range -- note the name, there is no `npcs` key, and reading a
missing key returns nothing and looks exactly like an empty world.

## Thieving chests

`chest_nature_rune` and friends are locs, opened with their own option. Loot
weights of `128` out of 128 mean **guaranteed**, not chance.

| Chest | Thieving | XP | Respawn | Loot |
| --- | --- | --- | --- | --- |
| 10 coins | 13 | 38 | 15 ticks | coins 10 |
| **Nature rune** | **28** | **250** | **30 ticks** | **1 nature rune + 3 coins, both guaranteed** |
| 50 coins | 43 | 1250 | 150 ticks | coins 50 |

The nature rune chest is the best nature rune tap in the game by a wide margin:
one rune every 30 ticks beats hobgoblins at 4 runes per 2-in-128 kill by orders
of magnitude, and no F2P shop stocks the rune at all.

**It spawns three times, and this is the part worth reading carefully:**

| Where | Coords | Level | What it costs to reach |
| --- | --- | --- | --- |
| Ardougne Castle, upper floor | (2614, 3314) | 1 | Thieving 28, plus the walk (below) |
| Ardougne | (2671, 3301) | 1 | Thieving 28, the walk, **and a way past a locked door** |
| Pirates' Hideout, deep Wilderness | (3042, 3949) | 0 | Thieving **39** + a lockpick, and a route |

The two Ardougne chests are guarded by townspeople, a priest, merchants and a
guard dog. The Wilderness one sits inside a compound with **ten aggressive
level-25 pirates** (23 HP each, max hit about 4-5, respawn 50 ticks) at
wilderness level ~54.

**An agent lost most of a day to the Wilderness one because a private note
claimed Ardougne was members-only and nobody had tested it.** Enumerate every
spawn of a thing before choosing which to chase.

## Ardougne is reachable overland. Walked, 2026-09-13.

This was an open question for days and the answer is yes. A character walked
**Draynor to Ardougne (2671,3301) in 33 legs, 1 detour, 2 replans**, arriving
with full health. Nothing about the trip needs members, a quest or a teleport.

**What made it look impossible was one closed gate.** At **(2935,3450)** and
**(2935,3451)**, on the Falador/Taverley boundary, stand `loc_1596` and
`loc_1597`. They have **no entry in `loc.pack`**, so every search for "gate",
"door" or "stile" along that boundary returns nothing. Live they report the name
**Gate** with a single **Open** option, and opening one flips the ids to
**1560/1561**.

Two characters treated that line as a wall for a whole day, and it is worth
being precise about why the evidence pointed the wrong way:

- `walkTo` west is refused from one tile away, exactly like a wall.
- The **terrain flags show the band as open**, so it is not terrain either.
- The loc data has no gate *by name*, because the gate has no name.

So it reads as neither wall nor terrain nor door, which is an easy thing to
conclude is simply the edge of the world. **Open the gate and walk through.**
These are the same ids as the Wilderness fence gates -- when a boundary refuses
a single step and the terrain says open, look for a nameless loc on the tile
and read its live options rather than searching the pack for a word.

## The (2671,3301) chest needs more than Thieving 28

The chest is on **level 1**, and its room is reached by the **Staircase at
(2673,3300)**, which stands inside a building whose door (`loc 131`, at
(2672,3298)) answers **"The door is locked."**

The nearby **Ladder at (2674,3309)** does go up, and a character with 99
Thieving picked the lock on `loc_2550` at (2674,3305) to reach it -- but it
lands in a **different** level-1 room that does not connect to the chest. From
(2671,3303), two tiles from the chest, the answer is still "I can't reach that!"

So the page's old claim that these chests cost "nothing beyond Thieving 28" is
wrong for this one. Untested: whether (2614,3314) in Ardougne Castle is more
open, and whether the locked door wants a key or a quest.

## Locked doors

`scripts/skill_thieving/configs/doors/locked_door.dbrow` is the whole table.
Picking one needs the level, and some need a **lockpick** in the inventory.

| Door | Thieving | XP | Lockpick |
| --- | --- | --- | --- |
| loc_2550 | 1 | 38 | no |
| loc_2556 | 13 | 150 | no |
| loc_2551 | 16 | 150 | no |
| loc_2557 | 23 | 250 | **yes** |
| east Ardougne sewer gates | 31 | 250 | no |
| **loc_2558 (Pirates' Hideout)** | **39** | **350** | **yes** |
| loc_2554 | 46 | 375 | no |
| loc_2555 | 61 | 500 | no |
| loc_2559 | 82 | 500 | **yes** |

**loc_2558 spawns at exactly (3038, 3956), (3041, 3959) and (3044, 3956)** —
the three doors of the Pirates' Hideout. So Thieving 28 opens the nature rune
chest but **cannot open the door that stands in front of it**; that needs 39
and a lockpick.

## Getting to the Pirates' Hideout

It cannot be walked to from the south. The barrier at z~3905 is the **Lava
Maze**, and a small-step sweep from **x3020 to x3122** found no gap anywhere;
the loc data for that whole band contains no gate, door, stile or bridge,
because lava is terrain rather than a loc.

The intended route is the **Wilderness teleport lever**. In this revision
`wildinlever` exists **once**, at **(2561, 3311) in Ardougne** — there is no
Edgeville lever yet — and it lands you at `wildoutlever`, **(3153, 3923)**, in
the Deserted Keep. From there the guides' directions match this world's data:
run north, **slash the web** (`bigweb_slashable`, locs at (3093, 3957) and
(3095, 3957) — any slash weapon does it), then run west to the compound doors.
The lever script carries no level or membership check, only a confirmation
dialog ("Yes I'm brave.").

**Five green dragons sit across the overland approach**, at (3078,3810),
(3092,3810), (3098,3821), (3107,3812) and (3118,3820) -- a band at z3810-3821
spanning x3078-3118. An agent died there. They are **npc id 941**, which is the
detail that matters: the dragon ids are not contiguous, red is 53, black 54 and
blue 55, so a preflight that checks an id *range* misses green entirely. Check
by name.

The Rogues that drop the lockpick are north of that band at (3076,3916) and
(3079,3909), so an overland trip to them crosses it. Note also that map data
alone reports **no route** from Edgeville (3093,3518) north to the Rogues: the
Wilderness wall and the Lava Maze close it, which is why the recorded route
goes east to the gate at (3224,3904) rather than straight north.

Note that both the lever and the two easy chests are in Ardougne, so Ardougne
access is the single gate on every nature rune plan.

## XP to levels

This world's curve is far flatter than RuneScape's; see `mechanics.md`. Level
99 is about **1,000,000 xp**. Using the **live** column: Men at 200 a success is
roughly 5,000 successes, Guards at 1170 is roughly 855, and Heroes at 6832 is
roughly **146**. The nature rune chest's 250 config becomes 625 live per 30
ticks.

The multiplier is already applied in the live column, so do not apply it twice.
