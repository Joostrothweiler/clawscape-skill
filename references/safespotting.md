# Safespotting and kiting

**Status: partially established. The failure mode is confirmed; the working
method is NOT yet proven.** Written down at this stage because the failure is
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

## The trap: attacking walks you out of your own safespot

This is the part that cost a character's life and is the reason to read this
page.

`interactNpc` with Attack **moves the character to the target**. It does not
fire from where you stand. So a character parked on a perfect safespot issues
one attack and is promptly carried into melee range, where the monster it was
hiding from hits it normally.

Measured at (2544,3413), ten attacks against a giant six tiles away:

    t+00  at (2541,3422)  hp 94
    t+01  at (2544,3408)  hp 94     <- left the safespot on the first attack
    ...
    t+09  at (2544,3408)  hp 76     <- 18 damage taken, safespot irrelevant

The safespot was correct. The attack command defeated it.

## What should work instead: attack, step back, attack

Mike's suggestion, and it follows directly from the above: do not try to stand
still. **Attack, then immediately walk back along the line away from the
target**, so the monster spends its turn closing while you are already out of
reach, then attack again as it arrives.

`hunt.py --kite N` implements this: after each attack it steps N tiles directly
away from the target's last known position.

**This has not yet completed a single verified cycle.** It was implemented, and
the character died before it ran -- of a stale health reading, not of the
method. Treat the mechanism as plausible and untested until a run shows health
flat across many kills. **Do not record it as working on the strength of this
page.**

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
