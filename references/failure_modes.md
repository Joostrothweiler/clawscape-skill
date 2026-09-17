# How agents fail here, and what catches each one

Every entry below actually happened, most of them more than once. They are
collected in one place because the expensive ones share a shape: **the world
tells you something false, or tells you nothing, and the agent believes it.**

Read the "signature" column. Recognising the signature is the whole skill; the
diagnosis is usually easy once you stop trusting the wrong signal.

## The big one: silence is not information

| What is really happening | What it looks like |
| --- | --- |
| Session dropped | every action accepted, nothing moves |
| Character is 18 tiles from its target | `train.py` reports `"dispatched": true` forever |
| Walking into a wall | `walkTo` refused, no message |
| Walking into water | `walkTo` refused, no message |
| Standing at a closed gate | `walkTo` refused, no message |
| Toll unpaid with an empty purse | dialog completes, crossing still refused |

**These are indistinguishable from each other and from success.** Every one of
them has cost this project hours. The guards below all exist to tell them apart.

### Judge a loop by whether the number moved

A training loop ran **thirty-plus rounds gaining zero xp** while reporting
`"dispatched": true` every time, because the character had been left 18 tiles
from the nearest guard. Dispatch means "the server accepted the request", never
"the thing happened".

**Guard:** compare the skill's experience before and after every round. Two flat
rounds means reposition, not continue. See `thieving.md`.

### A dropped session looks exactly like terrain

Imaginary walls were mapped around Falador this way, and a whole scripted
expedition once ran its full length against a dead connection, moving zero
tiles. When no recipe is running, nothing notices at all -- three characters sat
offline for hours with no error anywhere, because the error only appears when
something asks.

**Guard:** `recipes/keepalive.py`, run in the background for the whole session.
It reconnects and re-asserts combat style, and stays quiet unless something is
wrong. `walk.py` also reconnects mid-walk.

### Never read position mid-walk

`state` during a walk reports a tile the character is passing through. Deciding
on it produces confident, wrong conclusions like "it went backwards".

**Guard:** `walk.settled()` polls until two consecutive reads agree.

## Combat style silently reverts, and index is not identity

Style goes back to index 0 on reconnect. Auto-retaliate is on by default, so an
unattended character that gets attacked trains whatever index 0 happens to be.
**Arete's Attack went 43 to 57 and her combat level 75 to 80 this way** --
permanent, on a build that wanted neither.

Worse, **style indices are per-weapon**. On a scimitar index 1 is
Slash/Aggressive (Strength). On another weapon index 1 can be the Defence
style, and index 2 is Lunge, which trains Attack, Strength *and* Defence. Every
hardcoded `--style 1` is one weapon change away from ending a pure build.

**Guard:** read `combatStyle.styles[].trainsSkills` from live state and pick a
style that trains what you want and **nothing forbidden**. If none qualifies,
change nothing. `keepalive.choose_style()`, with tests.

## The map data lies in specific, knowable ways

### The LOC section cannot see terrain, but the MAP section can

Water, lava and cliffs are not locs. For a long time this was written up as
"terrain is unknowable", and every offline plan cheerfully crossed rivers. It is
knowable: MAP rows read `level x z: h<height> f<flags> u<underlay>` and **flag
bit 1 means blocked** (84.7% of live refusals carry it, 2.9% of walked tiles).

**Guard:** `mapdata.terrain_blocked()`, unioned into `blocked()`.

### Walls sit on tile edges, not on tiles

A character could not reach a ladder **one tile west**, because the LOC row on
her own tile was `1602 0` -- a timberwall, shape 0, rotation 0, a wall on her
west edge. Both tiles are perfectly standable, so no tile-level model can say
it. `blocked()` is therefore wrong in both directions: it forbids standing where
you can stand, and permits walking through a wall from the far side.

**Guard:** `mapdata.wall_edges()` and `solid_tiles()`, per level. Rotation is
**omitted when 0**, so a two-field LOC row is rotation 0, not missing data.

### Many things have no name

The Wilderness fence gates and the Falador/Taverley boundary gate are
`loc_1596`/`loc_1597` with **no entry in `loc.pack`**. Every search for "gate",
"door" or "stile" returns nothing, which reads as "there is no opening here".
One such gate was mistaken for the edge of the world by two characters for a
day; opening it took one call.

**Guard:** use `distinct_names()` and read the list, never grep for the word you
expect. When a boundary refuses a single step **and** the terrain flags say
open, look for a nameless loc on the tile and read its **live** options.

### Crops block movement and `blocked()` cannot see them

`mapdata.blocked()` catches barriers by keyword: lava, railing, wall, fence,
castle, hedge, crumbl, pileof, rubble, boulder, rock. **Wheat is not in that
list, and a wheat field is solid.** The tiles read `reachable: false` live and
refuse every step, but an offline path walks straight through them.

Measured in the Ardougne farmland on 2026-09-17: **395 crop tiles** in one
260x110 band that every planner treated as open ground. A route computed
through them refuses at the field edge and looks exactly like a closed gate, a
wall, or a dropped session.

**Guard:** add crop names to the blocker set for any route near a farm --
`wheat`, `barley`, `hops`, `potato`, `cabbage`, `onion`, `flax`, `corn`. And
treat a refusal beside a farm as a crop until proved otherwise, rather than
sweeping for a gate that is not there.

### Absence of a wall is not evidence; absence of a gate is

The asymmetry is the useful part. "No gate in the data" means there is nothing
to open. "No wall in the data" means nothing at all.

## Searching and reasoning

### A cheaper method is evidence about the method, never about the goal

The quietest failure in this file, because nothing breaks and no report is
wrong. A goal usually exists for several reasons. When a discovery makes one of
them cheap or unnecessary, the goal stops feeling urgent and drifts out of the
plan, even though the reasons the discovery did **not** address are still
there, and are now a larger share of what is left.

It happened on 2026-09-17. A moss giant camp was wanted for nature runes,
alchable drops and Ranged experience. A stackable alchemy feedstock turned up
that hour and killed the drops reason outright; the runes were already solved.
Ranged survived, and was the character's biggest gap by twenty levels, so the
camp had become **more** worth walking to, not less. Instead it stopped being
mentioned and the cheap thing got finished. The owner had to ask where the
camp had gone.

**Guard:** when something gets cheaper, enumerate the reasons the goal existed,
mark which ones actually died, re-rank on what survives, and **write the new
ranking into whatever file the next session reads.** A priority that changes
only inside one session's reasoning has not changed, it has been forgotten.
Silence is how priorities die here, the same way silence is how broken loops
hide, and the guard is the same: make it explicit, in a file.

### Never truncate a search you are about to conclude from

`grep | head -10` hid the one relevant row twice in this project: once a
`wildinlever`, once a gate that then cost hours. If you are about to say "there
is no X", you must have looked at every row.

### A negative is a hypothesis until tested

A private note claimed Ardougne was members-only. Nobody had tested it, an
agent lost most of a day to the far harder Wilderness alternative, and **the
claim was false** -- Ardougne was walked overland in 33 legs. Enumerate every
spawn of a thing before choosing which to chase, and cost the cheap route before
paying for the expensive one.

### A wrong "no route" is the expensive kind of wrong

It is indistinguishable from a closed world, so it reads as a fact about the
game rather than a fact about your search. A BFS box of 60 tiles reported "no
corridor" for a trip that exists; at 200 the same call returned a 791-tile
route. Be generous with search bounds -- a wide corridor costs BFS almost
nothing.

### Replanning without learning is a loop

A plan recomputed from the same inputs is the same plan, and the character
stalls on the identical tile forever. Anything that replans must fold in what
was just learned.

## Walking

### Long legs fail where short hops work

Especially in the northern Wilderness. Many recorded "walls" are probably this.
Indoors it is worse: multi-tile `walkTo` usually refuses outright.

### `walkTo` does its own pathing and ignores your plan

Give it a tile your plan says is adjacent and it may route some other way and
land elsewhere, quietly desynchronising the walk from the plan. Following a path
by firing `walkTo` at each tile in turn deviates and then walks nonsense --
observed twice in one session, 22 tiles of planning wasted each time.

**Guard:** indoors, step one tile at a time and **verify each step landed on the
intended tile**, aborting the moment it does not.

### `reachable` on a loc is unreliable in both directions

`false` for a bank booth that then opened fine; `true` for things that answered
"I can't reach that!". Treat it as a hint, never a decision.

### A walker that does not record teaches nobody

Several hundred tiles of exploration were lost to a hand-rolled walker that
logged nothing, after which `route.py` correctly answered
`unmapped_destination`.

**Guard:** use `walk.py`/`trek.py`, which record through `travel.py`'s `record()`
and feed the atlas on every settled read.

## The Wilderness

### Bank everything that is not kit

A character died carrying **25,215 coins** that served no purpose on the trip.
Death drops nearly everything. See `wilderness.md`.

### Food is not a survival plan

She ate three lobsters and died with **21 still in the bag**. Recipes that eat
at `--min-hp` restore health *between* steps, so when incoming damage beats one
lobster per step the trend is down regardless of how much food is carried. What
is missing is an abort rule, and nothing implements one yet.

### Preflight the destination, not only the route

The route preflight worked -- the path stayed 75 tiles clear of all five green
dragons. Rogues' Castle itself was never checked, and that is what killed her.

### Check for lethal NPCs **by name**, never by id range

The dragon ids are not contiguous: red 53, black 54, blue 55, and **green 941**.
A guard that checked a range missed green dragons entirely, and an agent died to
them.

### An option's `opIndex` is the index; its position in the list is not

`useInventoryItem` with the wrong `optionIndex` returns `success: true` and
does nothing. `alch.py` computed `list.index("Wield") + 1` and sent **1** for a
staff whose only option is `{"text": "Wield", "opIndex": 2}`, so the staff
never left the pack and **30 alchs in a row consumed nothing**. The same rule
already bit dialogue handling, where an option's own `index` is likewise not
its position.

**Guard:** read `opIndex` off the option you matched, then **verify the state
changed** -- for a wield, that the equipment slot now holds it. And where a
loop has an obvious canary, check it on the first iteration: `alch.py` now
stops if cast one gains no xp, and prints the last game message, which said
`"You do not have enough Fire Runes to cast this spell."` the whole time.

## Working on the repo

### `ruff` is for Python, never JSON

`ruff format` on `routes.json` added Python trailing commas and destroyed it.

### `atlas.json` and `routes.json` are written by every agent at once

Including ones running right now. **Merge, never overwrite** -- load both sides,
union them, and assert nothing was lost before committing.

**`git reset --hard` is an overwrite, and it does not feel like one.** On
2026-09-17 a `git checkout main` was refused because those two files were
dirty, and the reflex fix was `git reset --hard upstream/main`. That discarded a
session's worth of freshly folded map: 100 walked tiles and the hop log for a
mountain crossing nobody had ever recorded. `atlas.py fold` had already cleared
`observations.jsonl`, so there was nothing to re-fold and the data was simply
gone.

**Guard:** these two files are shared state, not build output. Before any
`reset --hard`, `checkout -f`, `clean`, or `stash drop` in this repo, commit
them or copy them out. If a branch switch is refused because they are dirty,
that refusal is the guard working.

### Branch from freshly fetched `upstream/main`

A fork's `main` goes stale the instant an upstream PR squash-merges, and a
**conflicting PR never runs CI at all** -- it sits there looking like slow CI.
This cost two rebuilt PRs in one session. If a PR shows no checks after a
minute, check `mergeable` before assuming CI is slow.

### Verify what you name, not just what you measure

A whole section was written up as "Falador" when every coordinate was
Edgeville's. The numbers were all correct, nothing contradicted the label, and
it would have sent the next agent 240 tiles to the wrong town. `routes.json`
landmarks answer it in one lookup.
