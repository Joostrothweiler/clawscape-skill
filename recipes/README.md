# Recipes

Scripts an agent runs instead of driving a loop a tick at a time. Each one
shells out to `../clawscape.py`, so it shares the same login, the same world
and the same one-action-per-character rule — there is nothing extra to
configure.

| Recipe | What it does |
| --- | --- |
| [`train.py`](train.py) | Repeats one interaction until a skill reaches a level, clearing level-up dialogs and stopping on death, low HP, a full inventory or a stall. |
| [`travel.py`](travel.py) | Walks further than one `walkTo` call safely handles, hopping in small steps and crossing whatever blocks the way (a Gate, a Stile, a dialog-gated border) instead of stopping at the first silent non-move. |

```sh
uv run recipes/train.py --character gorruk --npc goblin --option Attack \
    --skill Attack --target-level 20

uv run recipes/travel.py --character gorruk --x 3222 --z 3218
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
