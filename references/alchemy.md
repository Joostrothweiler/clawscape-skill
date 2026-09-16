# Alchemy: what to cast it on

Alchemy is the one Magic line worth pursuing here (see `magic.md`), and the
question nobody had answered is **what to alch**. This is that answer, read from
the world's own configs rather than from an outside wiki.

## The formula, from the spell itself

`scripts/skill_magic/scripts/spells/alchemy.rs2`:

    high alch:  max(scale(6, 10, oc_cost($item)), 1)   -- 60% of the item's cost
    low  alch:  max(scale(4, 10, oc_cost($item)), 1)   -- 40% of the item's cost

So **alch value is 0.6 x the `cost` field** in the item's `.obj` config. Nothing
else matters: not shop price, not what it sells for, not rarity.

Excluded by `is_alchable`: **nature runes, fire runes** (the spell's own
reagents), **coins** ("Coins are already made of gold"), and one joke item.

| Spell | Magic | Runes per cast | Live XP |
| --- | --- | --- | --- |
| Low alchemy | 21 | 1 nature + 3 fire | **775** |
| High alchemy | 55 | 1 nature + 5 fire | **1625** |

Live XP is the config value x2.5; see `mechanics.md` for the multiplier.

**Both spells confirmed live on 2026-09-16**, cast on Lobster (`cost=150`):
low alchemy paid **60 gp / 775 xp**, high alchemy **90 gp / 1625 xp**, one
nature rune each. A **Staff of fire** supplies the fire runes for free, so the
only consumable is the nature rune. Magic 50 -> 55 took **15 low alchs**, which
makes the level-55 gate far cheaper than it looks.

**Caution: about 1 cast in 5 is a silent no-op.** Ten dispatches all returned
`success: true` but only eight consumed an item and paid out. Count the item,
not the dispatch.

## Route three: alch what you already fish

Overlooked because it needs no combat and no travel. A **cooked Lobster's
`cost` is 150**, so it high-alchs for **90 gp** against the **37-38 gp** a
general store pays, and pays **1625 Magic xp** on top. For a character with
Fishing 99 and a working lobster circuit, that turns food into a renewable
alchemy feedstock and makes the whole loop self-supplying: fish it, cook it,
alch it. Keep a real food reserve before alching the stock down.

## Route one: kill things and alch the drops

**Moss giants are the best target in the game for this**, and not narrowly --
they drop the fuel as well as the goods. Full table from
`drop tables/scripts/moss_giant.rs2`, out of 128:

| /128 | Drop | Alch value |
| --- | --- | --- |
| 5 | black sq shield | **691** |
| 2 | mithril sword | 507 |
| 2 | mithril spear | 507 |
| 1 | steel kiteshield | 510 |
| 1 | steel arrow x30 | 216 |
| 2 | steel med helm | 180 |
| 2 | magic staff | 120 |
| **3** | **nature rune x6** | *the reagent itself* |
| 4 | law rune x3 | |
| 3 | chaos rune x7 | |
| 1 | death rune x3 | |
| 39 | coins (37 / 119 / 300) | |

That is roughly **53 gp of alchable loot per kill**, about **20 coins per kill**,
and **0.14 nature runes per kill** -- so the loop partly refuels itself. Kill
with Ranged, alch the drops, and three skills move at once.

**Where:** npc **112** (`mossgiant`), 22 spawns, **12 of them outside the
Wilderness** -- (2549,3408), (2554,3401), (2554,3409), (2556,3406) west of
Ardougne, and (2691,3215), (2692,3204) to the south. The Ardougne cluster is the
safest and sits beside the nature rune chest run.

Higher-value drops exist (black dragons drop 30 adamant javelins at 20/128,
worth 2880 alched) but they come from dragons and demons, which a **Defence 1
pure should not fight**. Moss giants are level 42 and safe at combat 80.

## Route two: mine it, smith it, alch it

This trains **three** skills -- Mining, Smithing and Magic -- from raw rock, and
needs no combat at all. Best product at each tier a character can reach, ranked
by alch value **per bar**, since bars are what the mining costs:

| Smithing | Item | Bars | Alch each | Alch per bar |
| --- | --- | --- | --- | --- |
| **48** | **steel platebody** | 5 | **1200** | **240** |
| 50 | mithril dagger | 1 | 195 | 195 |
| 33 | iron platebody | 5 | 336 | 67 |
| 18 | bronze platebody | 5 | 96 | 19 |

**Steel platebody is the target.** A steel bar is 1 iron ore + 2 coal, so the
chain is: mine iron and coal, smelt steel bars, smith platebodies at Smithing
48, alch them for 1200 each.

Rune items are far better (rune platebody alches for **39000**) but need
Smithing 85-99, which is a project rather than a plan.

## Which route

They are not exclusive and they fail differently:

- **Moss giants** need no skill training first, pay immediately, and drop nature
  runes. They need a weapon, food, and a character that can fight.
- **Mine and smith** needs Mining and Smithing raised from 1, which is slow, but
  it is safe, repeatable, and the only route that builds two new skills.

For a character that already fights well, moss giants pay from the first kill.
For one that cannot fight, or that wants Mining and Smithing anyway, the smithing
chain is strictly better than buying items to alch.

## The binding constraint is fire runes

Nature runes have no shop anywhere in F2P (see `thieving.md` for the chest).
**Fire runes do**: Port Sarim stocks 1000, and Varrock, the Mage Arena and
Yanille also sell them.

The permanent answer is the **staff of fire** (obj 1387, **1500 gp**, Zaff's in
Varrock, 2 in stock). It supplies the fire rune for every cast forever, which
turns alchemy into a one-input activity: nature runes only. Buying fire runes
works and is a treadmill; the staff is bought once.
