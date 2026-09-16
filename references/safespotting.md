# Safespotting and kiting

**Status: the mechanic is now measured. Kiting is disproven; a genuine
safespot is untested but no longer ruled out.** Written down at this stage because the failure is
the expensive part and somebody else will otherwise pay for it again.

## The idea

A melee monster that cannot path to any tile adjacent to you cannot hit you. If
you can attack it from there with Ranged or Magic, you take no damage at all,
which removes the food ceiling and makes farming indefinite rather than
bounded by how many lobsters fit in 28 slots.

## Safespots exist, and can be computed

They can be found from the map data rather than hunted for by hand. A tile P is
a safespot against a monster spawning at G when:

- P is walkable (not in `mapdata.terrain_blocked` or `solid_tiles`)
- no tile adjacent to P is reachable by a BFS from G over walkable tiles,
  respecting `mapdata.wall_edges`
- P is within weapon range of G

Run against the moss giant camp west of Ardougne this yields **24 candidates**,
for example **stand (2544,3413) against the giant at (2549,3408)**, range 5.

## A safespot is against ONE spawn, and attacking a second one throws it away

This is the operational catch, and it is easy to lose because the tile looks
like a property of the place rather than of the pairing. **It is computed per
spawn.** The BFS that proves nothing can reach you starts at G. A different
giant, standing somewhere else in the same camp, has its own reachable set, and
nothing in the computation says it cannot path to your tile. So the spot holds
only while you attack the one spawn it was solved for.

The failure is silent in the worst way: the first giant dies without touching
you, the loop picks the nearest remaining target, and that one walks straight
in. It will read as "the safespot stopped working" when what changed was the
target.

This is why **`hunt.py --safespot` requires `--target`**. Pass the exact spawn
coordinates and nothing else:

    python3 recipes/hunt.py --character arete --npc "Moss giant" \
        --safespot 2544,3413 --target 2549,3408

Range 5 there is comfortably inside an Oak longbow's measured 9 (below), so the
shot fires from the safespot without closing. **When the target dies, the right
move is to wait for that same spawn to respawn, not to retarget.** A camp with
one workable pairing is a camp with one giant's kill rate, and that is the
honest throughput to plan around.

**Worth checking live before the first trip:** a moss giant is level 42, and
the usual rule is that a non-Wilderness aggressive monster stops attacking once
the player's combat level passes roughly double its own. Arete is combat 85
against a threshold of 84, i.e. one level over the line. If that rule holds
here, the other giants ignore her entirely and only the attacked one is a
problem. That rule is **not confirmed for this world** -- treat it as a thing to
observe on arrival, not a safety margin to plan on.

## Attacking does NOT walk you out of your own safespot

An earlier revision of this page said it did, and concluded from that the whole
method was defeated. **That was wrong, and it took a safespot camp off the
table for no reason.** Measured live on 2026-09-16 with an Oak longbow, against
Varrock palace guards:

| Target distance when the attack was issued | What the character did |
| --- | --- |
| 3 tiles (inside bow range) | **did not move at all**, fired from standing; the guard walked to her |
| 14 tiles (outside bow range) | walked exactly **4 tiles**, stopped at **distance 9**, then stood and fired |

    t+0  me=(3227,3469)  dist 14
    t+2  me=(3223,3466)  dist 9    <- stopped here and stayed
    t+5  me=(3223,3466)  dist 1    <- the GUARD closed, not her

So the rule is: **`interactNpc` Attack walks you only far enough to bring the
target inside your weapon's range, and no further. Inside range you fire from
where you stand.** Oak longbow range measured at **9 tiles**.

The earlier observation that "looked like" being dragged to melee -- a
character at (2541,3422) ending up at (2544,3408) -- is this same rule with the
target out of range: it closed to range and stopped. It landed in melee because
the weapon's range was short, not because the attack overrides position.

**This means a computed safespot should hold**, as long as it satisfies the
third criterion above: within weapon range of the spawn. The 24 candidates at
the moss giant camp west of Ardougne were dismissed on a false premise and are
still worth testing.

## Kiting does not work, and is worse than standing still

Tested the same day, `hunt.py --kite 5` against the same guards, Ranged 69,
Defence 1, no armour:

    round 1  hp 88     round 4  hp 65     round 7  hp 52
    round 2  hp 79     round 5  hp 55
    round 3  hp 78     round 6  hp 50

95 -> 52 over 7 rounds, about **6 HP a round**. The melee baseline against the
same guards was 88 -> 45 over 28 rounds, about **1.5 HP a round**. Backing away
is worse than not bothering, and the reason follows from the rule above: the
attack already fires from where you stand, so stepping back buys nothing, and
the tiles spent walking are tiles not spent shooting while the monster closes
anyway.

**Kite is the wrong lever. The lever is terrain the monster cannot path
through.** Treat `--kite` as disproven and spend the effort on `--safespot`.

## Prayer is not a substitute

Protect from Melee (Prayer 43) is available and does reduce damage, but it
**drains**: cost 12 on a 5-tick timer, against a prayer pool equal to the Prayer
level. It buys a fight, not a camp. Useful while closing or retreating; not a
way to stand in melee indefinitely.

## Things worth doing while you are there

- **Bury the bones.** Every kill drops them, they occupy a slot, and burying is
  free Prayer xp. Confirmed working: Prayer 50 -> 51 inside ten kills.
- **Pick the arrows back up.** Every ranged shot is an arrow on the ground at
  the target's feet. A hunt that does not collect them runs out; one that does
  is close to self-sustaining. Confirmed: +25 arrows recovered over 10 rounds.
- Drops land at the **target's** feet, not yours, so a sweep has to walk to them
  -- `pickupItem` on something out of reach just answers "I can't reach that!".
