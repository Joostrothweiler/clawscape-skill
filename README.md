# clawscape-skill

A policy layer for [rs-sdk](https://github.com/MaxBittker/rs-sdk): rule ladders,
an outcome log, and a learner that reorders the parts of a ladder that were
always a guess.

rs-sdk gives agents a verified action surface and a headless client. What it
deliberately does not give them is a way to *decide* — its agents are imperative
scripts and Ralph-style loops. This repo is the layer above that: a fleet of
characters, each running a priority ladder on the engine's own tick callback,
recording what every action actually paid, and re-ranking itself while it runs.

Read [LESSONS.md](LESSONS.md) first. It is the most useful thing here.

## What it does

- **A ladder per character.** Rules are ordinary TypeScript with a `when` and a
  `then`. First match wins. Safety rungs sit above earning rungs, and the
  learner is not allowed to reorder them.
- **One Intent at a time.** A rule proposes one action plus the evidence that
  would prove it worked. Nothing else is considered until that resolves — by
  observed effect, by explicit rejection, or by a deadline. Never by the fact
  that a packet was written.
- **An outcome log.** Every resolved Intent is one JSON line: rule, resolution,
  ticks, milliseconds, XP, coins. This is the training set.
- **A learner.** A plain ε-greedy bandit over rules sharing a `group`, with
  recency decay and optimistic initialisation, deployed live every two minutes.
- **Roles.** Under a peak metric a fleet is one score, not five, so preparers
  concentrate their takings in a single scorer.

## Run it

The layer imports rs-sdk's own state collector, action executor and headless
client, so it lives inside an rs-sdk checkout:

```sh
git clone https://github.com/MaxBittker/rs-sdk.git
cd rs-sdk && bun install
cp -r /path/to/clawscape-skill/fleet server/webclient/src/fleet

# one directory per character, each with its own credentials
for n in cwsylas cwgorruk cwmorgra cwoakward cwthrain; do bun bots/create-bot.ts $n; done

cd server/webclient
bun src/fleet/run.ts cwsylas cwgorruk cwmorgra cwoakward cwthrain --minutes=60
```

The first name is the scorer; the rest hand their takings to it. Fresh accounts
walk themselves off Tutorial Island — there is no setup step.

Inspect what was learned at any point:

```sh
bun src/fleet/learn.ts --explain --dry-run
```

## Why it runs in-process

rs-sdk offers two ways to drive a headless client. Through the SDK gateway,
`bot.*` gives you verified helpers, but every action costs a WebSocket
round-trip plus a full state broadcast before the next one can be aimed — about
2.0s per pickpocket, measured. Driven in-process on the game-tick callback, the
same action costs the two ticks the engine actually needs.

We take the second path for the hot loop, because the rate at which agents can
act is what decides how much a run learns. Measured here: five characters in one
Bun process, each acting about once per tick.

The trade is that in-process code does not get `bot.*`, so anything needing a
long verified sequence — banking, the Grand Exchange, a two-sided trade — should
still go through the gateway. Both paths produce the same `BotWorldState` from
the same collector, so a ladder does not care which one it is running on.

## Layout

| File | Role |
| --- | --- |
| `fleet/types.ts` | Rule, Intent, Beliefs, Outcome — the vocabulary |
| `fleet/beliefs.ts` | one read-only view of the world per tick |
| `fleet/agent.ts` | the kernel: dispatch, judge, settle, record |
| `fleet/memory.ts` | the outcome log, and the peak-window score |
| `fleet/learn.ts` | the bandit |
| `fleet/policy.ts` | the learned rule order, as a diffable JSON file |
| `fleet/minds/prelude.ts` | rungs every character needs: unblock, and leave the island |
| `fleet/minds/thief.ts` | a worked ladder, including the hand-off |

## Status

Working and measured against the public demo server: five characters, learning
live, concentrating gold in one scorer.

Not yet built: the burst itself. The fleet accumulates but does not yet convert,
and converting is what a peak metric actually scores. That needs a batchable
skill — fletching or smithing — and it is the obvious next piece.

## History

This repo used to be a Python CLI wrapper with its own action recipes. That
substrate has been removed in favour of rs-sdk, which does the same job better
and is maintained. What survives is the part that was genuinely ours: the
ladder, the outcome log, the learner, and the lessons.
