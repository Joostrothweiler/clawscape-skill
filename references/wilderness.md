# The Wilderness

Written after a character with 99 Thieving, 99 Strength, combat level 80 and 24
lobsters died at Rogues' Castle on 2026-09-13 and lost 25,215 coins. Everything
here is the specific reason that happened, so the next agent does not repeat it.

## Carry nothing you are not willing to lose

She was carrying **25,215 coins** because she had been banking pickpocket profits
and nobody emptied the purse before the trip. Death drops everything except a
few items, so the coins were gone instantly and contributed nothing to the trip
in the first place.

**Bank everything that is not kit before crossing in.** Food, a weapon, and the
one or two items the objective needs. Nothing else. This is the cheapest rule on
this page and the one that was ignored.

## Eating is not a survival plan

The death log reads: `You eat the lobster.` / `It heals some health.` three times
over, and then `Oh dear you are dead!`. She had 21 lobsters left when she died.

A recipe that eats at `--min-hp` only restores health **between steps**, so when
incoming damage is faster than one lobster per step, health trends down no matter
how much food is in the bag. Food ran the clock; it did not win the fight.

**So a Wilderness recipe needs an abort rule, not just an eat rule:** if health
falls below the threshold *again within a few steps of eating*, the character is
losing and should leave, not carry on toward the objective. Nothing in
`walk.py`, `maze.py` or `trek.py` does this today -- they all treat food as
sufficient. Treat that as a known gap.

## Exposure time is the real risk, and the slow recipe maximises it

`maze.py` steps one tile at a time, deliberately, because that is how it gets
through terrain the map data cannot see. In safe country that is merely slow. In
the Wilderness it means standing in hostile territory for tens of minutes, and
**every extra minute is more chances to be attacked**.

The death happened during a `maze.py` leg, not a `walkTo` leg. Prefer long
`walkTo` legs in hostile ground even when they fail more often, and spend
`maze.py` only where there is no alternative -- or turn back.

## Preflight the destination, not only the route

The route was preflighted properly and it worked: five green dragons sit at
z3810-3821 (see `thieving.md`), the planned path stayed **75 tiles** clear of
the nearest one, and she passed them without incident.

What was not preflighted was the **destination**. Rogues' Castle sits at
(3276-3296, 3924-3939), around wilderness level 54, and it is not a quiet corner
-- it is a walled compound full of aggressive NPCs, and other players hunt there
precisely because rogues are worth pickpocketing.

**Check what lives where you are going, not just what lives on the way.**

## Getting there at all

From Edgeville the recorded approach is **east to the gate at (3224,3904)**, then
east along z~3903. Map data reports **no route** straight north from Edgeville to
the northern Wilderness: the Wilderness wall and the Lava Maze close it.

Note that the ground around (3340-3360, 3895-3915) is a trap for automated
walkers. Probed live from (3350,3905), **every direction was refused except
south-west**. A planner that keeps proposing west from there will push a
character east instead, which is how this trip drifted 60 tiles off course
before the end.

## What the trip was for

The only **lockpick** in the world drops from pickpocketing a **Rogue** (npc id
187, 22 spawns, all in the Wilderness) at roughly 3.9% a success. Two stand at
(3076,3916) and (3079,3909); the other twenty are at Rogues' Castle.

The lockpick gates `loc_2558`, the Pirates' Hideout door, which needs Thieving
39 *and* the lockpick, and behind it is the third nature rune chest at
(3042,3949).

**Before making this trip, read the two easier options first.** Both remaining
nature rune chests are in Ardougne at (2614,3314) and (2671,3301), need only
Thieving 28, and need no lockpick and no Wilderness at all. An agent already
lost most of a day to the Wilderness chest because a private note claimed
Ardougne was members-only and nobody had tested it. The map squares from Falador
to Ardougne form an unbroken chain, so that claim is still untested rather than
confirmed. **Test the cheap route before paying for the expensive one.**
