# Lessons

Things that cost a session to learn, written down so they cost you nothing.
Everything here was observed live against a running server. Where something is
inference rather than observation, it says so.

## Measurement

**Dispatch success is not effect.** The engine refuses ops it will not run —
player mid-action, stunned, target gone or out of view, bad option — by
answering `UNSET_MAP_FLAG` and nothing else. No message, no error. A blocking
modal is worse: the op is accepted and the trigger never runs. So "the packet
was written" tells you almost nothing, and a fleet making zero progress looks
perfectly healthy on every counter. Gate every action on an *observed* effect,
and use `state.opFeedback.opRejectedCount` as the closest thing to a negative
acknowledgement that exists.

This is the single most expensive idea in the repo. An earlier version of this
project measured "did we send it" and inherited that confusion into every
number downstream, including the reward signal.

**Take the XP baseline only after it stops moving.** Skills arrive after the
player does, and they arrive zeroed before they arrive correct. Sample too
early and the first action to resolve is credited with the character's entire
lifetime experience — observed here as *"6,305 xp in 11 pickpockets"*. That one
phantom row also set a fake peak-window score. Requiring two consecutive ticks
to agree costs one tick per session and removes the whole class of error.

**An unreachable target is a silent no-op, not a failure.** The client
pathfinds before every interaction and, when it cannot route, returns without
writing a packet — so the server never says "I can't reach that!" either. To a
learner this looks like an action that took time and paid nothing. Filter on
`reachable` before an action, not after.

**Never assume an option index.** Read the option's own `opIndex` off the
target. The same dialog publishes its buttons in different orders in different
places; skill dialogs publish four buttons *per product*, so arrow shafts are
option 4 of 12, not option 1. A hardcoded index is a silent no-op waiting to
happen.

## Reinforcement learning

**Credit must be causal, or you build a lazy agent.** We scored actions against
a *fleet-wide* potential, reasoning that a fleet with one shared goal should
share one reward. Measured live, a character whose rule found no target and did
nothing for eleven seconds scored **+269/s** — because two other characters
were working through those same seconds. The learner then promoted the rule
that had stalled it. A shared reward pays every agent for the fleet's progress,
so standing still scores as well as working.

Compute value from the acting character's own gains. Cross-character enabling
is real, but it belongs to reward-to-go along one character's own timeline, not
to a potential summed over everybody.

**Failure is evidence, not absence.** Count a rejected or timed-out action as a
trial that earned zero against the time it burned. If you only count successes,
a rule that fails *structurally* — there is no such NPC here, ever — stays
permanently "unmeasured", and optimistic initialisation keeps promoting it to
the top of the ladder forever. Trying an unknown arm first is right; never
noticing that it does not work is not. This stalled two characters for an
entire run.

**Potential-based shaping cannot see goods in transit.** A hand-off by dropping
lowers the giver's inventory the instant it happens, and raises the receiver's
only on its own next cycle — and in between, the goods sit on a tile that no
character snapshot can see. A potential built from snapshots therefore scores
the most useful act in a supply chain as destruction. Ours read **−3,025**.
Either model the ground as part of the state, or let reward-to-go carry the
credit for hand-offs and keep shaping to what it can actually observe.

**Fix the reward before reaching for more machinery.** Both failures above look
like arguments for hierarchical RL. They were arguments for a correct reward.
The bandit abstraction was fine throughout.

## The benchmark

**RuneBench scores the best 15-second window, not the total.** The metric is
deliberate — it exists to "reward agents that discover higher-level strategies,
beyond pure time-on-task". Published runs show a median peak-to-mean ratio
around 12×, with the best near 100×.

Two consequences that change the whole design:

1. **Preparation is free.** Everything before the scored window is unscored, so
   stockpiling costs nothing.
2. **Pick a batchable skill.** The winning shape is *stockpile, then burst*.
   Combat magic is close to the worst possible choice, because casting cannot
   be batched — every cast needs a target and a tick. Smithing, fletching,
   firemaking and enchanting all convert a pile of inputs into experience as
   fast as the client will accept clicks.

We spent two monitored runs maximising *sustained total* Magic XP — the metric
the benchmark explicitly rejected. Don't.

**Under a peak metric, a fleet is not five scores, it is one.** The right shape
is N−1 characters preparing, unscored, for the whole run, and one converting
everything in the scored window. That makes collaboration the dominant
strategy rather than a nicety.

## Mechanics

**A dropped item is private to whoever dropped it for about a minute.** It does
not despawn — an earlier version of this document claimed it did, and that was
wrong. It is simply invisible to everyone else for a while, which is why a
recipient standing on the same tile cannot see it.

The consequence bites: a character that drops a hand-off *can* still see it,
and will immediately pick it back up unless you explicitly blind it to its own
drops. That produces a hand-off that never happens, at full speed, looking
healthy on every counter.

**A modal replaces the inventory tab.** Inventory packets sent underneath one
are rejected as "component not visible", with no game message. Clear blocking
UI before anything else, and never click the interface's own close-window
component.

**A fresh account starts on Tutorial Island.** Nothing useful is routable from
there, so a ladder aimed at the mainland dispatches walk commands the server
discards — 300 actions for 0 xp while looking busy. Handle the tutorial as
rules in the ladder rather than as a setup script: a script has to be run and
remembered, a rule notices the island and leaves.

**The game is not buggy.** It is well-tested and complete. If something does
not work, the assumption is wrong. Investigate first, file a bug report after
you understand it.
