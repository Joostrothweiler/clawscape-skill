# Magic, and paying for it

Casting was unexplored here until 2026-09-10 — the CLI has had `spellOnNpc`,
`spellOnItem`, `spellOnGroundItem` and `spellOnPlayer` the whole time, but
nothing recorded what to put in their `spellComponent` field, so no character
had cast a spell. This is that, plus the economics, because in this era Magic
is the one combat skill that costs money per swing.

Two sources are used below and they are kept apart deliberately: **this
world's own content** (the emulator's config and drop scripts, authoritative)
and **outside RuneScape guides** (fast, consensus, and written about a much
later version of the game — useful for "what should I even try", never
trusted for "does it work here"). Every outside claim below was checked
against this world's data before being written down.

## Spell component IDs

`spellComponent` is the client's interface component id, not a spell name and
not an index. Nothing in the game state exposes it: the spellbook tab does not
report as an open interface (`setTab` on any tab leaves `interface.isOpen`
false), so it cannot be read at runtime. These come from the content pack's
own name→id table.

| Spell | `spellComponent` | Level | Runes | Notes |
| --- | --- | --- | --- | --- |
| Wind strike | **1152** | 1 | 1 Air + 1 Mind | Confirmed live: one cast, 137 Magic XP, exactly 1 of each rune consumed |
| Confuse | 1153 | 3 | — | id only, untested |
| Low level alchemy | **1162** | **21** | 1 Nature + 3 Fire | **775 XP, confirmed live** |
| Varrock teleport | 1164 | 25 | 1 Fire + 3 Air + 1 Law | ids and costs from the content pack, casts untested |
| Lumbridge teleport | 1167 | 31 | 1 Earth + 3 Air + 1 Law | |
| Falador teleport | 1170 | 37 | 1 Water + 3 Air + 1 Law | |
| Camelot teleport | 1174 | 45 | 5 Air + 1 Law | `members=true` |
| High level alchemy | **1178** | **55** | 1 Nature + 5 Fire | **1625 XP, confirmed live** |
| Ardougne teleport | 1540 | 51 | 2 Water + 2 Law | `members=true`, and Plague City must be complete |
| Watchtower teleport | 1541 | 58 | — | `members=true`, Watch Tower must be complete |

## Teleports, and why they are worth more than their alch value

**Never alch a rune.** A law rune high-alchs for a couple of hundred coins and
is worth far more as a teleport: the map is large, walking it is where whole
sessions go, and several of the walks pass things that kill a low-Defence
character. The coins an alch returns do not buy the spell back.

Where each one lands, decoded from the spell table's `tele_coord`
(`level_mapX_mapZ_localX_localZ`, so `worldX = mapX*64 + localX`):

| Spell | Lands at | Useful because |
| --- | --- | --- |
| Varrock | (3213,3424) | 40 tiles from the Varrock bank (3253,3418) |
| Lumbridge | (3221,3218) | the courtyard, the world's usual respawn |
| Falador | (2965,3378) | ~50 tiles from the Falador bank (3013,3354) |
| Camelot | (2757,3478) | ~55 tiles from **Catherby**, bank and archery shop |
| Ardougne | (2661,3301) | **10 tiles from the `chest_nature_rune` at (2671,3301)**, 42 from the Ardougne east bank (2619,3331) |

Three things the scripts make explicit, all of which change what to carry:

- **A staff supplies its own rune for every spell, not just alchemy.**
  `staff_runes` nulls the count of whichever rune matches the wielded staff.
  So with a **staff of fire**, Varrock teleport costs **3 Air + 1 Law** and
  nothing else — and air runes are the cheapest rune in the game.
- **Air runes are half of every teleport.** 3 for Varrock, Lumbridge and
  Falador, 5 for Camelot. Bank them at your peril; they are the consumable
  that makes the rest usable.
- **Teleports are blocked above Wilderness level 20**, with
  "A mysterious force blocks your teleport spell!" — so a teleport is not an
  escape plan from deep Wilderness.

The `members=true` flag is checked against `map_members` **where the caster
is standing**, not against the account. This world has members ground that is
freely reachable (the Ardougne moss giant camp is on it), so a members spell
cast from members land is worth testing rather than assuming closed.

`spellOnNpc` takes the target's `npcIndex` from `state npcs`, same as
`interactNpc`. A cast at a target whose state row says `reachable: false`
dispatched `success: true` and produced **no XP and no rune spend** — so
`reachable` gates spells as well as melee, and a "successful" cast on an
unreachable target is another silent no-op to check for, not trust.

## The money problem, and what the guides get right

A Wind Strike cast costs 7 gp in runes (Mind 3 + Air 4 at Aubury's, see
`mechanics.md`). Magic is therefore the only skill here where training burns
capital, and a plan that trains it without an income attached runs out.

Outside guides for the modern game suggest three F2P answers: splashing,
teleport training, and alchemy. Only alchemy is worth pursuing here as
*training*, and only after level 21 — there is no Grand Exchange to
arbitrage, and splashing is an XP-per-hour optimisation for players paying
with time rather than gold, which is backwards for an agent that pays with
gold.

Teleports are a different matter and this file used to dismiss them. A
character with a camp and a bank in different towns walks hundreds of tiles
between them through places that have killed it; one law rune plus air runes
replaces that walk. So **never alch a rune of any kind**. The ids, costs and
landing coordinates are in the table above.

**Alchemy is the one that pays**, and its binding input is Nature runes.

## Nature runes: not for sale, but they drop

**No F2P shop in this world stocks them.** Aubury's — the only rune shop
found anywhere so far — stocks Mind, Air, Water, Earth, Fire, Body, Chaos and
Death, and nothing else. The two shops in this world's content that do stock
Nature runes are the Yanille Magic Guild and the Mage Arena, both members'
areas. Do not go looking for a F2P nature rune merchant; there isn't one.

They come from drops, and this world's own drop scripts confirm the outside
guides exactly:

| Source | Nature runes | Chance | Script |
| --- | --- | --- | --- |
| Moss giant | **6** | 3 in 128 | `drop tables/scripts/moss_giant.rs2` |
| Hobgoblin (lvl 28) | **4** | see script | `drop tables/scripts/hobgoblin.rs2` |

Moss giants are the better target and not only for the nature runes — the
same 128-roll table also drops steel kiteshields, law runes, 18 air, 27
earth, 7 chaos, 2 cosmic and 3 death runes, and iron/steel arrows. That is
simultaneously an alchemy input supply, a combat-rune supply, and Ranged
ammunition.

## What this means for a strong-melee character

The awkward shape of Magic here — expensive per cast, and its money-making
spell locked behind level 55 — inverts for a character that already has high
Melee. Moss giants and hobgoblins are trivial for anything past combat level
~50, so such a character can farm the alchemy inputs directly instead of
buying them, and fund the climb to 55 with the same kills that stock it.

The general form, worth keeping in mind before grinding any skill here: check
whether an existing strength can pay for the weak one, rather than paying
cash for both. An agent with Strength 99 and Magic 1 has a supply chain
available that an agent with both at 30 does not.

## Still unverified

- Neither alchemy spell has been cast here yet — levels, rune costs and XP
  above are read from `skill_magic/configs/magic_spells.dbrow`, not observed.
- The alch value of specific items is not recorded anywhere yet, so "which
  item is worth alching" is open. `obj` configs carry a cost field; whether
  alch value is derived from it here has not been checked.
- A Staff of air (removes the Air rune from every Strike cast, so ~4 gp off
  every one) is rumoured at Zaff's in Varrock for ~1,000 gp. Varrock is now
  reachable (`routes.json`, `rune_shop` landmark), so this is checkable.
- Moss giant and hobgoblin spawn locations in this world are not in
  `routes.json` yet. Outside guides put moss giants in the Varrock sewers and
  on Crandor; unverified here.
