# Recipes

Scripts an agent runs instead of driving a loop a tick at a time. Each one
shells out to `../clawscape.py`, so it shares the same login, the same world
and the same one-action-per-character rule — there is nothing extra to
configure.

| Recipe | What it does |
| --- | --- |
| [`train.py`](train.py) | Repeats one interaction until a skill reaches a level, clearing level-up dialogs and stopping on death, low HP, a full inventory or a stall. |
| [`travel.py`](travel.py) | Walks further than one `walkTo` call safely handles, hopping in small steps and crossing whatever blocks the way (a Gate, a Stile, a dialog-gated border) instead of stopping at the first silent non-move. |
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

`routes.json` is world knowledge, true for every character. What one character
did, promised or became belongs in its own journal instead — see
[identity](../references/identity.md) — and a recipe that runs long enough to
be worth remembering can add a line with
`clawscape.py identity note episode --text "..."`.
