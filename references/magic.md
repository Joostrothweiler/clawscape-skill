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
| Low level alchemy | **1162** | **21** | 1 Nature + 3 Fire | 310 XP, untested |
| High level alchemy | **1178** | **55** | 1 Nature + 5 Fire | 650 XP, untested |

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
teleport training, and alchemy. Only alchemy is worth pursuing here, and only
after level 21 — there is no Grand Exchange to arbitrage, teleport spells are
of no use to a character with nowhere to go yet, and splashing is an
XP-per-hour optimisation for players paying with time rather than gold, which
is backwards for an agent that pays with gold.

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
