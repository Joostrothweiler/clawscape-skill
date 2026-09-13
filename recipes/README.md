# Recipes

Scripts an agent runs instead of driving a loop a tick at a time. Each one
shells out to `../clawscape.py`, so it shares the same login, the same world
and the same one-action-per-character rule — there is nothing extra to
configure.

## Before anything else, read how agents fail here

[`references/failure_modes.md`](../references/failure_modes.md) collects every
way this project has actually lost hours: silent non-moves that look identical
to walls, dropped sessions that look like terrain, `"dispatched": true` on a
loop that gained nothing for thirty rounds, nameless gates mistaken for the edge
of the world, and a combat style that reverts on reconnect. Most of them are the
same shape -- the world says nothing, and the agent believes something. Reading
it first is much cheaper than rediscovering any single entry.

| Recipe | What it does |
| --- | --- |
| [`train.py`](train.py) | Repeats one interaction until a skill reaches a level, clearing level-up dialogs and stopping on death, low HP, a full inventory or a stall. |
| [`travel.py`](travel.py) | Walks further than one `walkTo` call safely handles, hopping in small steps and crossing whatever blocks the way (a Gate, a Stile, a dialog-gated border) instead of stopping at the first silent non-move. |
| [`shop.py`](shop.py) | Visits `--waypoint`s looking for a shop NPC and buys matching stock, saving the spot to `routes.json` under `--landmark`. Handles shops that open by `Talk-to` plus a dialogue answer rather than a Trade option (`--dialog-choice`), loops `shopBuy` because it caps at ~10 units per call, buys round-robin across shelves so a spell's runes arrive in ratio, and verifies every purchase against the inventory rather than the reported amount. |
| [`route.py`](route.py) | Walks somewhere far by planning over tiles this world has *already walked*: nodes are tiles stood on, edges are hops that happened, and the shortest chain is handed to `travel.py` a leg at a time. Replaces hand-picking waypoints out of `routes.json`, and refuses to invent a route rather than walking a character at a wall. |
| [`trade.py`](trade.py) | Moves items between two characters through the real trade interface, run on both sides at once. Gates every step on `modalInterface` and proves the transfer from an inventory delta, because each screen reports success whether or not anything moved. Use it instead of a drop relay for anything valuable — dropped items despawn. |
| [`harvest.py`](harvest.py) | Repeatedly interacts with a respawning loc, **polling for it to reappear** instead of sleeping a fixed interval. Measured on the nature rune chest: a fixed `wait 32` between opens gave **0.4 items/min**, polling gave **3.9** — same chest, same minute. Reports yield per minute, and warns when a round produces nothing, because an interaction that 'succeeded' is not an item in the bag. |
| [`indoor.py`](indoor.py) | Walks inside buildings and on upper floors, one **verified** tile at a time. `walkTo` does its own pathing and ignores your plan, so firing it down a planned path desynchronises and then walks nonsense; this checks every single step landed on the intended tile and replans from wherever it actually is. Plans over `wall_edges()` because a wall sits on a tile *edge* — a character was once refused a ladder one tile away with both tiles standable. `--use locId,x,z` picks the approach tile itself rather than trusting `reachable`. |
| [`keepalive.py`](keepalive.py) | Watches characters for the whole session: reconnects dropped ones, and re-asserts a combat style that trains what you want and **never** a forbidden skill. Sessions drop silently and style reverts to index 0 on reconnect, so an unattended character can train a skill its build forbids while every log line looks fine. Style is chosen by reading `trainsSkills` from live state, because style indices are per-weapon and a hardcoded index is one weapon change away from training Defence. |
| [`mind.py`](mind.py) | Runs a character from a [mind file](minds/) — goals that drop themselves when their condition holds, and rules that pick the next recipe from the situation rather than from a fixed order. Records every stop reason as a fact the next cycle can ask about. |

```sh
uv run recipes/train.py --character gorruk --npc goblin --option Attack \
    --skill Attack --target-level 20

uv run recipes/travel.py --character gorruk --x 3222 --z 3218

uv run recipes/mind.py --character gorruk --mind recipes/minds/example.json --loop
```

## Deciding instead of listing

A recipe repeats one thing. Chaining recipes into an ordered list is the
obvious next step and the wrong one: the order is fixed when the file is
written, so the character keeps attacking after its runes run out, or retries
the fight that just nearly killed it, because that is what comes next. What
to do depends on the situation, and the situation is not in the list.

[`mind.py`](mind.py) takes the shape from GOAL, an agent language built on
beliefs, goals and rules:

```json
{
  "goals": [{"name": "attack_20", "satisfied": "level('Attack') >= 20"}],
  "rules": [
    {
      "name": "retreat_after_a_beating",
      "when": "failed_recently('train', 'low_hp', 900)",
      "then": {"recipe": "travel", "argv": ["--x", "3230", "--z", "3295"]}
    },
    {
      "name": "fight_the_goblins",
      "when": "",
      "then": {"recipe": "train", "argv": ["--npc", "goblin", "..."]}
    }
  ]
}
```

- A **goal** is a condition, re-read every cycle. Nothing has to be told the
  run is finished, and a goal that stops holding comes back on its own.
- A **rule** is `when` -> `then`, in priority order; the first condition that
  holds runs its recipe. An empty `when` is the catch-all, so it goes last.
- Every **stop reason becomes a fact** in `memory.jsonl`, which is what makes
  `failed_recently('train', 'low_hp', 900)` above a question worth asking.
  A cooldown is an ordinary condition here, not a special case in a runner.

`mind.py`'s own docstring lists everything a condition may ask;
[`minds/example.json`](minds/example.json) is a worked one. Reach for this
once a character's routine has settled into something that has to react —
a single recipe is still the right answer to a goal that is only a loop.

### The catch-all must be an action, never a wait

This is the one mistake that quietly wastes a whole run, and it is worth
stating on its own because the engine cannot catch it: **a mind whose
catch-all rule does nothing will do nothing, forever, and report success
every cycle while it happens.**

A live mind file for a character training Magic used "check chat for a
resupply hint" as its catch-all. Over one run it chose rules like this:

| times chosen | rule | outcome |
| --- | --- | --- |
| 6,877 | `wait_for_a_hint` | `no_hint` ×6,874 |
| 78 | `sweep_the_ground` | collected |
| 77 | `return_to_basecamp` | arrived |
| 46 | `cast_while_stocked` | `no_target` ×43 |

97% of 7,078 cycles were a no-op waiting on a delivery that no rule could
cause. The character idled next to hostile monsters, dropped to 1 HP and died,
and every line of the log looked healthy. Nothing was broken — the rules simply
had no answer to "I have run out of the thing I consume", so they picked the
only rule that always matched.

So, when writing the last rule:

- **Make it do something with a destination or a target.** Walking to a known
  rendezvous is a fine catch-all; polling a channel is not. If the character
  genuinely depends on another, the catch-all should still *move it to where a
  handoff can happen* rather than idle wherever it stands.
- **Give the resource problem its own rule, phrased as an errand.** "Out of
  runes and holding coins → go buy" beats "out of runes → wait". A mind that
  can only consume and never acquire will always stall.
- **Check every input the chosen recipe consumes.** A cast rule gated on Mind
  runes alone chose `cast` 46 times with zero Air runes and returned
  `no_castable_spell` each time. Gate on all of them.
- **Watch HP in a rule that fires from anywhere.** A retreat rule gated on
  "not at basecamp" never fires for a character already standing in the danger
  it should be fleeing. `hp_ratio < 0.5` with no position condition is the
  version that works, and `travel.py` to a tile already reached is a cheap
  no-op, so there is no cost to always allowing it.

`--dry-run --explain` prints every rule considered and the one chosen, against
live state, without acting. Run it once after editing a mind file: if the
answer is your catch-all, the file is not ready.

### A charter is a constraint on argv, not a note

If a character's charter forbids something — a mage that never melees, even in
retaliation — then no rule may dispatch a recipe that can do it. `train.py` and
`farm.py` take `--option Attack`, so a rule reaching for either to "earn a
little gold" is a breach however the note above it is worded, and prose in the
mind file does not restrain the runner. Audit the `argv` a mind can actually
emit, not its comments. `cast.py` is safe here by construction: it never falls
back to melee or ranged.

A charter that rules out every income route also means the character cannot
fund itself, and its mind file has to say who does instead.

## Running a fleet: one actor per character, enforced

`sh recipes/restart_all.sh` stops and relaunches a `mind.py --loop` for every
file in `minds/` (skipping `example.json`), logging to
`logs/<character>_mind.log`. Extra flags are forwarded, so
`sh recipes/restart_all.sh --patience 8` works.

It exists because retyping `pkill` and `nohup ... &` per character is the most
repeated and error-prone action this project needs — but the reason it kills in
**two steps** is worth understanding before hand-rolling a replacement.

`mind.py` only checks its `--stop-file` *between* cycles, and while a cycle is
running the work is happening in a child recipe process — `travel.py`,
`cast.py`, `shop.py` — which is the thing actually holding the character.
So signalling the parent leaves that child acting for as long as its round
lasts, and starting a fresh loop immediately puts **two actors on one
character**. The world does not serialise them for you: their observations and
actions interleave, each reads state the other just changed, and both report
success throughout.

Observed live, twice in one session: two `mind.py` loops on one character, each
with its own `travel.py`, walking it in opposite directions. It is easy to
cause by accident — removing the stop-file before the old loop has noticed it
is enough — and it does not announce itself in either log.

So the sequence is: create the stop-file, kill the parent, kill any recipe
still pinned to that character, **verify nothing matching `--character NAME`
remains**, and only then launch. The script refuses to start rather than
double up if anything is still holding a character. When in doubt:

```sh
pgrep -fl -- --character          # every process currently holding a character
```

## Writing one

A recipe earns its place when a goal is a loop and every round would otherwise
cost the agent a full observe-decide-act exchange. Keep to the shape
`train.py` uses:

- **One JSON object per line.** A checkpoint per round, then a final `done`
  line naming why it stopped. The agent reads the log, not the ticks.
- **Say why it stopped, in one machine-readable word.** `target_reached`,
  `died`, `no_progress`, `dialog_choice`. A recipe that stops without a reason
  just moves the guesswork.
- **Re-read the target every round.** Indexes and option menus are rebuilt
  per observation; a remembered `optionIndex` is how a grind trains nothing
  while reporting success.
- **Stop on anything that needs a decision** rather than deciding for the
  owner: a dialog with real choices, a death, an empty quiver, a full pack.
- **Exit 0 only on success.** 2 when it stopped early, 1 for a usage or world
  error, so a harness can branch without parsing.
- **Never sell, drop or trade** to keep a loop going.

## Accumulating world knowledge

`travel.py` reads and writes [`routes.json`](routes.json): confirmed
landmarks, boundary crossings and their exact mechanism (open a gate, climb a
stile, talk through a toll dialog), and an `open_problems` log of spots that
turned out not to be solvable by retrying. It updates that file on every run,
success or failure, specifically so the next run — by any character, in any
session — doesn't re-discover the same crossing or re-probe the same dead end
from scratch. If you add a recipe that does its own multi-step navigation or
world discovery, consider whether it should read from and write back to the
same file rather than starting blind.

`mind.py` writes `memory.jsonl` the same way, and for the same reason: one
line per outcome, appended by whichever character produced it, so a stop
reason is something the next cycle can query rather than prose someone has to
read. It is runtime state, not source — it is not committed.

### `open_problems` is map data, not a list of impossible moves

Worth stating plainly, because reading it the obvious way throws away more than
half the map. `travel.py` files a failed *journey* under `open_problems` — but
the `hops` inside that record are movements that really happened; the character
stood on each of those tiles in turn. Only the trip as a whole failed.

Built from `confirmed_paths` alone the graph is 1,301 edges in 5 disconnected
components. The hops recorded inside `open_problems` add **1,529 more** — more
than the confirmed set. Any reader that navigates by this file should use both,
and prefer confirmed hops only as a tie-break.

Two traps come with that, both of which produced confidently wrong routes
before they were fixed in [`route.py`](route.py):

- **The `to` field of a failed journey was never reached.** Treating
  `last_hop → to` as an edge invents a hop straight to the destination. It made
  every plan end in a single 135-tile stride onto the goal tile.
- **Sanity-check hop length.** `walkTo` caps at ~7-8 tiles and the one known
  exception is 6-9, so an edge much longer than that is a recording artefact
  rather than a movement.

Once both are excluded, the graph tells the truth — including unwelcome truths.
It currently says the southern world (1,613 tiles, up to z≈3380) and the
Varrock cluster containing Aubury's Rune Shop (32 tiles, z 3353-3402) **share
no recorded hop**: every journey in the northern cluster *starts* there, so
nobody has ever walked between them. That is worth far more than a plan that
walks a character into a boundary, and it names the frontier to explore.

`routes.json` is world knowledge, true for every character. What one character
did, promised or became belongs in its own journal instead — see
[identity](../references/identity.md) — and a recipe that runs long enough to
be worth remembering can add a line with
`clawscape.py identity note episode --text "..."`.

## Navigating terrain that refuses to be walked

Three recipes were added after one character spent most of a day concluding
that a region was impassable when it was not. They are the other half of
[`travel.py`](travel.py) and [`route.py`](route.py).

### [`mapdata.py`](mapdata.py) — ask the world where something is

A library and CLI over the content pack that
[world_data.md](../references/world_data.md) describes. Clone it once and point
`$CLAWSCAPE_CONTENT` at it.

    python3 recipes/mapdata.py spawns 53 --section NPC     # every red dragon
    python3 recipes/mapdata.py spawns 1597                 # every gate of that id
    python3 recipes/mapdata.py band 3195 3230 3895 3910 --names-only

**Use `--names-only` before you grep for a word.** Many locs have **no name**:
the Wilderness fence gates are `loc_1596`/`loc_1597` with no entry in
`loc.pack`, so searching for "gate", "door" or "stile" returns nothing and
invites the conclusion that no opening exists. Reading the distinct-name list
finds them. The same habit surfaces `railing` as the fence and `lavabubbles` as
the real obstacle.

**And check the route for what will kill you** before pointing anything at a
destination: `spawns 53/54/55 --section NPC` for red, black and blue dragons.

### [`walk.py`](walk.py) — travel, and write down what you walked

One long `walkTo` per leg, letting the server path, which is right for open
ground where `travel.py`'s small hops are wrong. It records every hop through
`travel.py`'s own `record()`, so the walk feeds `route.py`'s graph.

    python3 recipes/walk.py --character NAME \
        --waypoints "3060,3545;3100,3645;3140,3745" --min-hp 60

**A walker that does not log is worse than useless.** Several hundred tiles were
once explored with a private walker that wrote nothing; `route.py` then answered
`unmapped_destination` and the whole route was lost. It also never reads
position mid-walk — `state` during a walk reports a tile being passed through,
and deciding on those coordinates produces phantom "it went backwards" results.

### [`maze.py`](maze.py) — cross a field of obstacles, and learn it

For ground that is not a wall with a gap but scattered obstacles with walkable
tiles between them. It plans a BFS over `mapdata.blocked()` and walks it a tile
at a time; every tile the world actually refuses is written to a persistent
learned-blocked set and the path is replanned around it.

    python3 recipes/maze.py --character NAME --to "3201,3853" --min-hp 60

**Replanning without learning is a loop**: the identical plan stalls on the
identical tile, forever. The learned set is what converges, and it is kept
between runs, so a region gets cheaper each time anyone crosses it. This is what
finally crossed the Lava Maze after long-range walks, short hops and hand-rolled
pathfinders had all failed.

## [`atlas.py`](atlas.py) — knowing more each session than the last

`routes.json` is a travel log: what journeys were made. The atlas is the map
those journeys add up to, plus a dictionary of what things are. It exists so
that nobody starts from scratch.

    play  ->  observe()  ->  observations.jsonl  ->  fold  ->  atlas.json
                  ^                                              |
                  +---------------- brief / frontier ------------+

**Observation is passive, which is the whole trick.** `walk.py` and `maze.py`
call `atlas.observe()` on every settled state read, so simply moving records the
tiles stood on and every loc and npc that came into view, with ids, options and
coordinates. Nothing is learned on purpose, so nothing is forgotten by accident.

    python3 recipes/atlas.py brief        # start here: what is known, where the gaps are
    python3 recipes/atlas.py fold         # merge this session's observations in
    python3 recipes/atlas.py frontier     # walkable tiles with unknown neighbours
    python3 recipes/atlas.py unnamed      # objects seen live that still need an alias
    python3 recipes/atlas.py describe 1597
    python3 recipes/atlas.py name 1597 --alias wilderness_fence_gate_l --kind gate
    python3 recipes/atlas.py crossing 2558 --verb Open --requires "Thieving 39 + lockpick"

### Why the schema is shaped like this

**A refusal is not a wall.** A tile can refuse because of terrain, because a
gate wants opening, or because the character lacks a level or an item. Recording
the Pirates' Hideout door as blocked would tell everyone it is impassable when it
needs Thieving 39 and a lockpick. Requirement-gated passages are **crossings
with a `requires`**, never blockers, and `blocked()` deliberately excludes them.

**One failure is not evidence.** A monster standing on a tile refuses it once.
Blocks are believed only after repeated independent refusals, and a tile someone
later stands on clears its block outright — direct evidence always wins.

**Objects are keyed by id, not name.** Many locs have no name: the Wilderness
fence gates are `1596`/`1597` with no entry in `loc.pack`, which is why
searching for "gate" found nothing and cost a day. `unnamed` lists what has been
seen but not yet described, so the dictionary has a visible to-do list.

**Crossing verbs are data.** Open, Cross, Slash, Push, Climb-over and the
dialog-toll live in `crossings`, so a walker can enumerate the ways past a
barrier instead of probing only for "Open" — which is how a walker once reported
`stuck` on a dock with a gangplank underneath it.

### The session ritual

Start with `brief`. Plan with `route.py` over what is already known. Play — the
observing happens by itself. End with `fold`, and commit the atlas along with
`routes.json`. `frontier` then names the specific tiles where the map runs out,
which turns "go explore" into a destination.
