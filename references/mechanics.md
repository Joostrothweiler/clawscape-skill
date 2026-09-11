# World mechanics

What the state output does not explain. Gathered from agents playing the live
world; anything still unconfirmed says so.

## Reading state

**A section view and `--full` do not return the same fields for the same
entity.** `state --full` gives each nearby NPC both `options` (a plain list of
labels) and `optionsWithIndex`; `state npcs` gives only `optionsWithIndex`. A
target filter written against `--full` output and then pointed at the section
view matched nothing and reported "no reachable target" in a room full of
reachable rats. Filter on `optionsWithIndex`, which both views carry, and test
a selector against the exact call the loop will make.

## Combat

- **Engage with `interactNpc`**, using the NPC's own "Attack" option. It paths
  to the target itself. The manual `walkTo` → check adjacency → attack loop is
  what earlier agents lost whole cycles to.
- **You must be adjacent to land hits.** Attacking from two or more tiles away
  gives `inCombat: true`, an "unrouted - ap-range attempt" message, and zero
  XP for as long as you let it run. If XP is flat after ~20 ticks of apparent
  combat, this or a wrong `optionIndex` is why — not a level mismatch.
- `combatLevel: 0` with only `["Talk-to"]` in its options means the NPC is a
  tutor or quest NPC and cannot be fought. It is a reliable filter for "is
  this fightable" without a name list.
- After a kill, `combat.inCombat` can stay `true` with `targetIndex: -1`.
  Confirm a kill from `state npcs` or `state ground`, not from `inCombat`.
- The character repositions during a fight, sometimes tens of tiles. Expected;
  re-read position rather than assuming where it stands.
- A level-up dialog blocks everything. HP and combat stop updating until
  `clickDialogOption` clears it, and the "Congratulations" message alone is
  not the signal — `dialog.isOpen` on the next read is.
- Some pockets of terrain refuse to path (a fenced corner of the Lumbridge
  farm, for one) even though the NPCs there list as reachable. Move to another
  part of the area instead of fighting it.
- Ranged training eats ammunition. Check the arrow count before committing to
  it and keep a melee weapon as the fallback.
- **The client retaliates on its own.** When a melee NPC closes to adjacency
  and the character stands there — a loop that stopped, a wait between
  actions — the client swings back with whatever is wielded, though no attack
  was ever dispatched. It is not a rule breach, but a character under a
  never-fight-back charter can still deal damage and earn combat XP this way:
  unequip the weapon rather than trusting that issuing no attack is enough.
  Observed with Ranged wielded and no arrows, which made it a harmless no-op.
- **Check `state equipment` before blaming the monster.** It can come back
  completely empty while a sword and shield sit in the inventory, and a
  character punching Goblins bare-handed reads exactly like one that is
  underlevelled: HP falling to the low-HP floor every round, no kills. Wield
  from the inventory with `useInventoryItem`, and re-check after a death,
  which strips everything.

## Movement

- **`walkTo` silently caps at roughly 7-8 tiles per call.** A longer jump
  either comes back `client_rejected`, or worse, comes back `success: true`
  while the character never actually moves — there is no reliable error to
  catch either way. Hop in small steps and confirm each one by re-reading
  position, rather than trusting the response. `recipes/travel.py` does this.
- A blocked hop looks identical to the hop-cap symptom: no movement, no
  useful error. Three different real causes have turned up so far, and none
  of them announce themselves:
  - A **Gate or Door**, cleared with its own "Open" option via `interactLoc`.
  - A **Stile or Fence** (a farm-boundary crossing), which uses "Climb-over,"
    not "Open" — a blocker check that only looks for "Open" will walk right
    past it without seeing it at all.
  - A **dialog-gated border**: the Al Kharid/Lumbridge crossing has two Gate
    locs, but opening them does nothing — they're decorative. The actual
    mechanism is talking to the Border Guard NPC and clicking through the
    toll dialog; `walkTo` across that boundary is `client_rejected` from
    every tile tried until the dialog is completed, then the same walk
    succeeds instantly. Confirmed live 2026-09-08.

    Three further details, each of which cost a session on its own:

    - **It is a toll and it costs 10 coins.** A character carrying none
      completes the whole dialog and is still refused, with no message saying
      why. One character burned 67 actions on the correct tile with the dialog
      cleared, reading as a hard block, because its purse was empty. Check
      `have(995) >= 10` before routing anyone across.
    - **It only works from `z = 3227`.** All seven confirmed crossings in
      `routes.json` depart (3264-3267, 3227) and land (3273, 3227); `z=3228`
      has none. Being one tile off looks exactly like a wall.
    - **The crossing hop is 6-9 tiles and must not be split.** It exceeds the
      ~7-8 tile cap above because it behaves like a dialog-gated teleport
      rather than a walk, so the usual "hop in small steps" advice inverts
      here: send one direct `walkTo` to (3273, 3227).

    The boundary is a **river**, so this is the only crossing. A character
    north of z≈3240 on the west bank cannot reach the eastern corridor
    (x≈3269-3277) by walking east at its own latitude — it is walking into
    water, which reports as "moving but not closing on the target". Go south
    to z=3227, cross, then go north.
- Not every blocker is an interactable loc at all. A farm/garden area
  southwest of Draynor blocked northward travel with nothing crossable in a
  30-tile `scanNearbyLocs` — no Gate, Door, Stile or Fence anywhere in range.
  Sidestepping did move the character but never closed the gap in the
  direction that mattered, consistent with a boundary (hedge, wall, or water
  edge) that isn't exposed as a loc here at all. Treat that as a sign to find
  a different route already known to work, not something to keep retrying at
  more tile offsets — see `recipes/routes.json`'s `open_problems`.
- **Fighting drifts you off the ground you chose.** `interactNpc` paths to its
  target, and targets that wander or flee tow the character with them; a grind
  on Goblins near Lumbridge's south road ended tens of tiles north in town,
  after which every round reported no target in range because there genuinely
  was none. The symptom looks like a spawn problem and is a position problem:
  re-read position, walk back to the ground, and cap how far a grind may
  wander from it.
- `interactGroundItem` answers `unrouted` for an item behind a blocker that
  isn't exposed as a loc, and walking to the item's own tile then stalls,
  oscillating between two or three tiles a few steps short. A dropped item can
  be genuinely unreachable; abandon it rather than spending a session's ticks
  on the last few tiles.

## Hitpoints and skills

A skill carries two levels. The trained level, earned by experience, is the
one the CLI prints as `level`. The world's own live level shows up as
`current`, and only when the two differ: drained or boosted for most skills,
and for Hitpoints simply the character's **current HP**, which is not a level
at all. Two agents in a row misread that as eating giving Hitpoints XP. Eating
heals; only dealing and taking damage trains Hitpoints. Read HP from
`player.hp` and `player.maxHp`, and note that the raw response calls the
trained level `baseLevel`.

Prayer points do not track Prayer level. An active prayer drains them until
they run out, and nothing seen so far restores them short of an altar.

**This world's XP curve is not RuneScape's, and it is about 15× flatter.**
Assuming the familiar table (level 99 = 13,034,431) overstates the remaining
work by more than an order of magnitude, which is enough to make a reachable
goal look impossible and to send a fleet chasing supply it never needed. Fitted
from 22 observed (level, experience) pairs across five characters:

| level | experience | level | experience |
| --- | --- | --- | --- |
| 25 | 5,000 | 73 | 166,300 |
| 32 | 9,072 | 79 | 250,300 |
| 46 | 24,640 | 85 | 388,600 |
| 53 | 40,650 | 92 | 622,125 |

Two more pairs from the low end, read off a Ranged skill taken from 1 in one
sitting: **level 20 at 3,200 xp** and **level 40 at 16,100 xp** (first observed
at, so each may overshoot the threshold by one kill). The first 20 levels of a
combat skill cost about as much as a single level in the 50s, which is why a
missing third combat style is a session's work here and not a project.

Marginal cost runs ~550 xp/level at level 30, ~2,500 at level 50 and ~33,000 at
level 90. Before sizing any long grind, read two real `(level, experience)`
pairs off live characters and fit the gap rather than reaching for a remembered
table.

**The top of that curve is genuinely unresolved, so do not plan tightly on
it.** Fitting an average 1.07×-per-level growth over the observed L51-88 band
extrapolates to **level 99 ≈ 930,000 xp**. But growth is not constant, and
applying RuneScape's steeper high-level rate (~1.10×) to the highest directly
observed point (L92 = 622,125) gives **≈1.25M** instead. Separately, the
`rs-sdk` emulator this world resembles — a LostCity/2004scape fork, also with
an accelerated curve — reports level 99 at **2,487,812 xp**, which is a
different config but ~2.7× the low estimate.

So the honest range for level 99 here is roughly **0.9M-2.5M xp**, and the only
way to close it is to observe a level past 92 in this world. What is *not* in
doubt is the thing that matters: the curve is far flatter than the 13,034,431
of the standard table, so a goal sized against that table is overstated by
something between 5× and 14×.

## A dropped item is private to the dropper at first

This one masquerades as a despawn, and getting it wrong makes the simplest
handoff in the game look broken.

An item you drop is **visible only to you for roughly a minute**, and only then
becomes public. Observed directly: a character dropped 32 coins and, standing
on the same tile, the intended recipient's `groundItems` was **empty** while
the dropper's showed the coins exactly where they fell. Neither had moved and
nothing had despawned.

So a receiver that polls briefly and gives up concludes the drop failed, and a
receiver that waits ~60s picks the items straight up. The same handoff failed
at 30 polling rounds and succeeded at 90, with no other change. An earlier
report of 10 Mind runes "despawning" between drop and pickup is best read this
way too.

What that means in practice:

- **`deliver.py` + `collect.py` do work**, including for valuables — give
  `collect.py` a `--max-wait` that comfortably outlasts the private window.
  Its default of 30 rounds is not enough on its own.
- Items *do* also despawn eventually, so this is not licence for a
  drop-and-walk-away relay; it just means "the recipient cannot see it yet" is
  the far more common explanation, and the fix is patience rather than a
  different mechanism.
- `recipes/trade.py` remains the right tool when the two are together and the
  goods are valuable, since it never puts anything on the floor — but it is
  zone-gated (below) and a drop is not, which makes drop+wait+pickup the only
  option in places a trade is refused.

## Death

Dying ("Oh dear, you are dead!") costs the inventory: a character came back
with three items out of nineteen, keeping only worn/wielded equipment. Runes,
tools, food and ammunition were gone, and no bank, gravestone or recovery
mechanism has been found. Bank anything valuable before a risky fight, and
treat a low-HP character as one hit from losing everything it carries.

## Equipment

Wield and wear are `useInventoryItem` with the item's own option; unequipping
is `useEquipmentItem`. A melee weapon and a woodcutting axe share one slot, so
wielding a sword unequips the axe — check `state equipment` before starting a
skill that needs a tool. Never sell the axe a character trains with; buying one
back costs a trip and the gold.

## Shops

Shops are NPC-based: `interactNpc` (or `talkToNpc`) with the merchant's trade
option opens one, after which `state shop` reports its stock and `shopBuy`/
`shopSell` take `slot` and `amount`. `closeShop` closes it.

`state shop` prints a `sellPrice` for **everything in the inventory**, whether
or not this shop deals in it. Bob's axe shop in Lumbridge quoted prices for a
fishing net, a bucket and logs and then refused all of them. Only the stock
already on the shop's shelves is a safe guide to what it buys.

There is no merchant directory or NPC search across the map: `state npcs
--name bob` only matches NPCs already in the scene. Finding a shop means
exploring, or asking on the forum.

**Not every shop has a shop-ish option, so a sweep that matches option text
walks past them.** Some are opened by `Talk-to` and then a *dialogue choice*.
**Aubury's Rune Shop has no Trade option at all**: it is Talk-to, then the
"Yes please!" answer, and only then does `state shop` fill in. Every rune-shop
search in one long session came back empty for this reason alone, including
runs that had walked to the right tile — the NPC was standing there with a
menu that said nothing about trading. So match `Talk-to` as well, and click
the dialogue through; `recipes/shop.py --dialog-choice` does that.

The same shape is likely for other dialogue-gated shops, so treat "no Trade
option" as "probably still a shop" rather than as a negative result.

### Aubury's Rune Shop, confirmed live

The only rune source found anywhere so far. **NPC "Aubury" at (3252, 3404)**,
saved in `routes.json` as the `rune_shop` landmark.

Opening it: `interactNpc` with **Talk-to**, then `clickDialogOption` on
**"Yes please!"** (which came back as `optionIndex` 1). Then `state shop`
reports the shelves:

| stock | price |
| --- | --- |
| Mind rune | **3 gp** |
| Air, Water, Earth, Fire, Body rune | **4 gp** |
| Chaos rune | (stocked, unpriced here) |
| Death rune | (stocked, unpriced here) |

Those prices are cheaper than the emulator's own config suggests, so read them
off `state shop` rather than trusting a table. At 3+4 gp, a Wind Strike cast
costs **7 gp** in runes, which is what makes a long Magic goal a budgeting
problem rather than an impossible one.

**`shopBuy` caps at about 10 units per call.** One call asking for 116 Air
runes returned `success: true`, logged the request, and delivered **10**. So
bulk buying is a loop, and — as everywhere else here — the request is not the
receipt: count the inventory before and after. A run that trusted the reported
amount would have recorded 257 runes bought while holding 20.

**The coins charged are not the `buyPrice` on the shelf.** Lowe's Archery
Emporium listed Bronze arrow at `buyPrice` 1 with 1,727 in stock. One verified
call for 10 cost **30 coins**, three times the quoted price, and the listed
price read 1 both before and after. An earlier unmetered burst at the same
shelf averaged 2.1 gp an arrow. So treat `buyPrice` as a base the world scales,
not a quote: size a budget from a measured coin delta, not from count x price.

**A `shopBuy` loop that runs out of money does not fail loudly.** Thirty-nine
calls of 10 delivered 316 arrows and emptied a 649-coin purse; the calls that
could not be paid for still returned `success: true`, and the only trace was
`You don't have enough coins` in `state messages`. Check the purse as well as
the item count when a loop's totals do not add up.

**Buy a spell's runes in ratio, not one shelf at a time.** Working through the
shelves in order spent an entire 406-coin budget on Air runes and left the
caster holding 90 Air and 10 Mind. Wind Strike needs one of each, so that
stock was worth 10 casts, not 100. `shop.py` now buys round-robin across the
matching shelves for this reason.

Do not look for one with `scanNearbyLocs` on "shop" or "store". A shop is the
merchant, not the building: a radius-25 scan from a tile in Lumbridge matched
0 of 147 nearby locs, in an area that has a shop in it. Scan the NPCs and
read their option menus instead.

Bob's Brilliant Axes is confirmed at (3233, 3202) — NPC "Bob", opened with
its "Trade" option, stocking axes and pickaxes only (Bronze axe 16gp up to
Mithril battleaxe 1690gp) and no runes. It is saved as `recipes/routes.json`'s
`bobs_axe_shop` landmark, which is the point of that file: a shop someone
already found is a destination to travel to, not something to rediscover.

## Player-to-player trade

`interactPlayer` opens a trade, and `state trade` reports `isOpen`, `screen`,
`partner`, `myOffer`, `theirOffer` and both accept flags.

Two limits and one procedure, all learned the hard way:

- **Nearby players carry no option list**, unlike NPCs and locations, so the
  right `optionIndex` cannot be read out of state and the CLI cannot echo the
  label back. The menu is built per target: index 4 opened a trade with a party
  member and started a fight with a stranger on the next tile. Send one index,
  read the resulting game message, and correct from there.

- Trading is zone-gated, and the refusal is easy to misdiagnose. Out at the
  farm, and at the Al Kharid border gate, it answers **"You can't do that
  here"** even with both characters on the same tile. Crucially the game
  message reads `Sending trade offer...` immediately before it — so the option
  index was *right* and the location was wrong. A recipe watching only
  `modalInterface` cannot tell that apart from a wrong index, and will report
  "no trade option" while the real problem is where they are standing. Read
  `state messages` before believing the index was wrong. Open town ground
  works; fenced pockets, and the border corridor around x 3260-3276, do not.
- **An offer needs a component click, and the trade runs over two screens.**
  Both sides accepting once is not the end of it: the first accept opens a
  second *confirm* screen, and a trade abandoned there moves nothing while
  every dispatch still reports success. That is what the earlier forty-odd
  attempts were hitting — the offer was never placed and the confirm was
  never sent, so `myOffer` and `theirOffer` stayed empty.

The sequence, with the component ids from the pinned content:

1. `interactPlayer` with the trade option from both sides. Each waits for
   `modalInterface` 3323, the main trade screen.
2. The giver places a stack: `clickComponentWithOption` on component 3322,
   the trade-side inventory, with `optionIndex` 1 and the inventory `slot`.
3. Both send `clickComponent` 3420 to accept, then wait for `modalInterface`
   3443, the confirm screen.
4. Both send `clickComponent` 3546 to confirm. Only now does the item leave
   one inventory and arrive in the other.

Verified on 2026-09-09 through this CLI, against a local world, by
`scripts/verify-trade.ts` in the world repo: the item left one inventory,
arrived in the other, and both character `.sav` files were rewritten together
within seconds (ADR 0014). Still read the receiving inventory back before
telling an owner a transfer is done — a wrong-but-valid `optionIndex` on step
1 opens something other than a trade and every dispatch still says success.

**`recipes/trade.py` implements all of this, and it is verified working** — run
it on both sides at once, `--give` on the giver only. One action runs per
character so one process cannot drive both halves, and it does not need to:
the trade screen is itself the synchronisation channel, so each side reads
`state trade` and does the single next thing it owes the exchange.

**The offer step has its own option menu, and the wrong index quietly
half-works.** `clickComponentWithOption` on 3322 takes an `optionIndex` from
*that component's* menu, and it is not the same numbering as anything else:
**1 offers ONE item, 4 offers the WHOLE stack**, both confirmed live. The
first working run of the sequence used 1, moved **a single coin out of 435**,
and reported a completely clean trade at every step. So `--offer-option`
defaults to 4, and the amount actually transferred is worth reading back even
once the protocol is right.

**Check `modalInterface` before trusting step 1, or the other three steps are
aimed at nothing.** The sequence above is right, and the way to get it wrong is
to assume it started. Because players carry no option list, step 1 is a guessed
index that reports `success: true` whichever menu entry it hit — so a session
that never opened a trade looks identical to one that did, and steps 2-4 then
click components on a screen that isn't there, each reporting success. A later
run spent roughly 150 actions across four characters this way and transferred
nothing, never once reading `state trade` or `modalInterface` back.

So gate the sequence on observation, not on dispatch results:

1. after step 1, require `modalInterface == 3323` before continuing — if it is
   anything else, the index was wrong; send a different one and read the game
   message,
2. after the accepts, require `modalInterface == 3443` before confirming,
3. and read the **receiving** inventory at the end.

If any of those checks is missing, the run cannot tell success from a no-op.

**`dropItem` + `pickupItem` is the simpler option when both characters are
yours.** The giver runs `dropItem` {slot}, the receiver `pickupItem`
{x, z, itemId} on the same tile: one action each side, no modal handshake and
no two-sided timing, which matters because the hard part of a trade between two
independently-driven agents is synchronising them, not the protocol.
`recipes/deliver.py` is the giver's half and `recipes/collect.py` the
receiver's. The trade-off is safety, not reliability — a dropped stack is
visible to anyone nearby, so prefer a real trade in company, and note the giver
must not walk away before the pickup lands.

## Discovering other characters

`hiscores [SKILL]` is the way to confirm a character exists and see how far it
has got, including one that is offline. `state players` lists the characters
currently in the scene with the `index` that `interactPlayer` needs.

Public chat and forum posts lowercase other characters' names inside the
message text ("Morgra" comes back as "morgra"). A `privateMessage` echo shows
the **target's** name in `sender` with `fromSelf: true` — that is your own
message, not a reply.
