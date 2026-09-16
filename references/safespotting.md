# Safespotting

**Status: solved, and it was never about terrain.** The mechanism is the
monster's leash, it is written down in the world's own npc config, and it works
in open grass.

## The rule, in one line

> Stand on **open ground the monster could walk to**, further from its **spawn
> tile** than its `maxrange` and closer than your weapon's `attackrange`, with a
> clear line of sight. It is willing to come and not allowed to, so it never
> arrives -- and because the ground between you is walkable, your attack still
> lands.

The "could walk to" is not a detail. A tile the monster cannot path to is a
tile you cannot shoot from; see below. The safespot has to be somewhere it
*would* reach if only it were permitted, which is why this works in open grass
and never behind a wall.

For Arete against moss giants that is a three-tile window: `maxrange` 5, oak
longbow `attackrange` 10, so **stand 8, 9 or 10 tiles from the spawn**.

## The other method is dead, and this time from both sides

The previous revision defined a safespot as a tile the monster cannot *path*
to, and quoted "24 candidates at the moss giant camp west of Ardougne". Both
halves of that are wrong, and the second half is worth knowing because it is
the obvious idea and it costs a trip to find out.

**The number was not reproducible.** `recipes/safespot.py` now does that
computation for real, and run over **every moss giant camp in the world** the
terrain method returns exactly **one** usable tile -- on Crandor, behind a
quest. At the Ardougne camp it returns **zero**, under a four-way BFS and an
eight-way one alike. The camp is open grass; nothing there is unreachable. So
the live attempt that "failed" there was not defeated by some attack mechanic,
it was standing on a tile that was never a safespot.

**And an unreachable target cannot be attacked at all.** Tested directly on
2026-09-16 in the Edgeville dungeon, from a corridor at (3150,9904) with a wall
between, against moss giants reading `reachable: false`:

    12 attacks, at distances 5 to 10, every one:
      "Interacting with NPC #2692 (unrouted - ap-range attempt)"
      Ranged xp gained: 0        HP lost: 0

Twelve rounds, well inside the bow's range of 10, and she neither took a hit
nor landed one. **The wall that stops the monster stops the arrow.** The engine
wants a walkable route to the target, not merely a line to it, and this
confirms from the other direction what was already recorded in
`mechanics.md`: `reachable` is a precondition for every attack style, not a
hint.

So the terrain method is not merely rare, it is self-defeating: the property
that makes a tile safe is the same property that makes the target
unattackable. **Stop looking for walls. Look at `maxrange`.**

## What the world's own scripts say

`scripts/skill_combat/scripts/player/player_combat.rs2`:

    [apnpc2,_] @player_combat_start_ap;

    [label,player_combat_start_ap]
    def_int $attackrange = ~player_attackrange(inv_getobj(worn, ^wearpos_rhand));
    if (($attackrange <= 1 & ~player_in_combat_check = false)
        | npc_range(coord) > $attackrange) {
        p_aprange($attackrange);
        return;
    }
    @player_combat_start;

The attack fires **from where you stand**. `p_aprange` -- the thing that walks
you in -- runs only when the target is *further away* than the weapon reaches.
Being dragged into melee is the out-of-range branch, not the normal one.

`attackrange` is an obj param, not something to measure:

| weapon | attackrange |
| --- | --- |
| all longbows | **10** |
| all shortbows | 7 |
| autocast magic | 10 |

Longrange style adds 2, capped at 10 -- **and trains Defence**, so on a pure it
is never worth the tile.

And the leash is an npc param, `maxrange` in `scripts/_unpack/all.npc`:

| npc | vislevel | wanderrange | maxrange |
| --- | --- | --- | --- |
| Moss giant | 48 | 3 | **5** |
| Guard | 21 | 2 | 7 |
| Giant rat | 6 | 6 | 8 |
| Thief | 16 | 7 | 10 |
| Skeleton | 22 | 9 | 11 |
| Deadly red spider | 31 | 10 | 12 |
| Goblin | 5 | 15 | 17 |

Moss giants have the tightest leash of anything worth killing, which is what
makes them the natural safespot target rather than merely a rich one.

## Measured live, 2026-09-16, Oak longbow against Varrock guards

The independent variable is the distance at the moment the attack is issued,
recorded live rather than assumed, because the guard moves between samples.

| distance | line of sight | tiles the character moved |
| --- | --- | --- |
| 3 | clear | 0 |
| 4 | clear | 0 |
| 6 | clear | 0 |
| 7 | clear | 0 |
| 8 | clear | 0 |
| 9 | clear | 0 |
| 10 | clear | 0 |
| 8 | clear | **7** |
| 8 | blocked | 4 |
| 9 | blocked | 4 |
| 11 | clear | 4 (out of range: correct) |
| 13 | blocked | 16 |

Two things fall out of that, and the second is the operational one:

- **Inside `attackrange` with a clear line, the attack fires from standing.**
  Every blocked-line sample walked her in, 4 to 16 tiles. Line of sight, not
  distance, is what decides whether a tile holds.
- **About one attack in six still closes anyway.** The two distance-8
  clear-line samples are from the same tile against the same target, one moved
  0 and one moved 7. The likely cause is the target moving between the state
  read and the dispatch, so the engine evaluated a line we never saw. **A hunt
  loop must therefore re-assert its tile after every attack.** Against a
  leashed monster that correction is permanent rather than a postponement,
  because stepping back outside `maxrange` breaks contact for good.

## Using `recipes/safespot.py`

    python3 recipes/safespot.py --npc mossgiant --range 10 --combat-level 85

It reports, per spawn, the tiles inside weapon range, outside every nearby
hostile's leash circle, with a clear line. Three things it does that are worth
knowing:

- **A safespot is a pairing, not a place.** The leash circle it clears is the
  target's; every other spawn has its own. At the Ardougne camp the four giants
  sit 5 to 7 tiles apart, so a tile 8 from one can be 4 from another -- and the
  other is the one that kills you. This is why `hunt.py --safespot` requires
  `--target`, and why **when the pinned giant dies the right move is to wait
  for that same spawn**, not to retarget. One pairing is one giant's kill rate.
- **`--target` is the SPAWN tile, not where the monster is standing.** It
  wanders `wanderrange` tiles, so an exact match pins nothing; `--target-radius`
  defaults to a moss giant's 5.
- **Things that cannot attack are not threats.** An earlier pass counted
  fishing spots and sheep herders as hazards and reported every tile at the
  Ardougne camp compromised. Only spawns the world gives an `Attack` option
  count, and those whose `vislevel * 2` is under our combat level are flagged
  `likely_passive` -- they will not start a fight, though the threshold is the
  usual rule rather than one confirmed in this world.

## Kiting is still disproven

`hunt.py --kite 5` against the same guards cost about **6 HP a round** against
**1.5** for standing and meleeing. It follows directly from the rule above: the
attack already fires from where you stand, so stepping back buys nothing and
the monster closes anyway. **Kite is the wrong lever. The leash is the lever.**

## Prayer is not a substitute

Protect from Melee (Prayer 43) reduces damage but drains 12 on a 5-tick timer
against a pool equal to the Prayer level. It buys a fight, not a camp.

## Things worth doing while you are there

- **Bury the bones.** Every kill drops them, they take a slot, burying is free
  Prayer xp. Confirmed: Prayer 50 to 51 inside ten kills.
- **Pick the arrows back up.** Every shot is an arrow at the target's feet. A
  hunt that collects them is close to self-sustaining: +25 recovered over 10
  rounds.
- Drops land at the **target's** feet, not yours, so a sweep has to walk to
  them. Against a leashed monster that walk crosses into its circle, so sweep
  between kills, not during one.
