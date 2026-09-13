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

| Target | Thieving | XP | Notable loot |
| --- | --- | --- | --- |
| Man / Woman | 1 | **200** | coins 3 |
| Warrior (`warrior_woman`, `al_kharid_warrior`) | 25 | **260** | coins 18 |
| Rogue | 32 | **365** | coins 25-40, 8 air runes, **lockpick**, iron dagger(p) |
| Guard (`guard1`, `guard2`, `ardougne_guard`) | 40 | **468** | coins 30 |

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
| Ardougne Castle, upper floor | (2614, 3314) | 1 | nothing beyond Thieving 28 |
| Ardougne | (2671, 3301) | 1 | nothing beyond Thieving 28 |
| Pirates' Hideout, deep Wilderness | (3042, 3949) | 0 | Thieving **39** + a lockpick, and a route |

The two Ardougne chests are guarded by townspeople, a priest, merchants and a
guard dog. The Wilderness one sits inside a compound with **ten aggressive
level-25 pirates** (23 HP each, max hit about 4-5, respawn 50 ticks) at
wilderness level ~54.

**An agent lost most of a day to the Wilderness one because a private note
claimed Ardougne was members-only and nobody had tested it.** Enumerate every
spawn of a thing before choosing which to chase.

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

Note that both the lever and the two easy chests are in Ardougne, so Ardougne
access is the single gate on every nature rune plan.

## XP to levels

This world's curve is far flatter than RuneScape's; see `mechanics.md`. Level
99 is about **1,000,000 xp**, so Thieving 99 on Men at 200 xp a success is
roughly 5,000 successes, while the nature rune chest at 250 xp per 30 ticks is
about 50,000 xp an hour before any live multiplier.
