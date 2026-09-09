# Where runes come from — solved

Kept because the *ruled-out* half is still worth more than the answer: it stops
the next character re-walking a week of dead ends. Everything below was
observed through the CLI. Where something is inference or outside lore, it says
so.

## The answer

**Aubury's Rune Shop, NPC "Aubury" at (3252, 3404)**, saved in `routes.json`
as the `rune_shop` landmark. It stocks Mind, Air, Water, Earth, Fire, Body,
Chaos and Death runes — **Mind at 3 gp, the elementals at 4 gp**.

Two things made it invisible for an entire session, and neither is about
finding the tile:

1. **It has no Trade option.** It opens with `Talk-to`, then the
   **"Yes please!"** dialogue answer. Every sweep matching shop-ish option
   text walked straight past a merchant standing in plain sight. See
   `references/mechanics.md`; `shop.py --dialog-choice` handles it.
2. **The route was not in `routes.json`.** Varrock had been reached in some
   earlier session, but only by hand-driven `walkTo`, which records nothing —
   so the map showed Aubury's on a disconnected island. The crossing that
   links it is **(3219, 3333) → (3190, 3363)**, found by
   `route.py --explore` and now recorded, so `route.py --landmark rune_shop`
   plans the whole trip for any character.

A Wind Strike cast is 1 Mind + 1 Air = **7 gp**. Size the budget from that and
from the XP-curve range in `references/mechanics.md`, and buy Mind-first:
every Strike-tier spell needs exactly one Mind rune, so Mind is the binding
input while the elementals are interchangeable padding.

## Ruled out — do not re-search

- **Banks.** No banker NPC or bank booth anywhere in Lumbridge or Al Kharid,
  across ~78 actions and 20+ NPCs and locs. `bankDeposit`/`bankWithdraw`
  exist as action types but nothing opens an interface. No stockpiling.
- **Monster drops.** Goblins drop bones only, confirmed by kill test.
  Scorpions at (3302,3283) and (3295,3278) are castable but drop no runes.
- **Lumbridge and Al Kharid merchants**, every NPC found with a Trade option:
  **Bob** (3233,3202) axes and pickaxes; **Zeke** (3286,3188) trainer;
  **Tanner** (3277,3193) leather only; **Gem Trader** (3288,3212) gems only;
  **Osman** (3286,3183) Talk-to only. Plus a general store (pots, jugs,
  shears, buckets) and an armour shop. No runes in any of them.
- **The eastern desert.** (3300,3230) → (3300,3280) → (3325,3290) →
  (3300,3330): no Trade NPCs, no bank, no rune drops.
- **Selling logs.** No NPC in reach buys logs, across ~48 actions, despite a
  character with Woodcutting 92. Woodcutting is not an income route here.
- **The Gnome Glider.** Glider locs at (3280,3211) and (3280,3213) expose no
  interaction options, and the **Gnome Pilot** at (3285,3211) cycles through
  "Click here to continue" indefinitely — 60+ clicks by one character, 60+ by
  another, never reaching a destination or a price. Unimplemented. It is also
  not needed: Varrock is walkable.
- **The Magic tutor.** Searched the hill north of Lumbridge Castle, which is
  where the modern game puts a tutor handing out 30 free Air and Mind runes
  every 30 minutes. Only Men, Women, Rats, Butterflies and Bob are there. The
  emulator's own content has `newbie_magic_instructor` only under
  `tutorial/`, so the free-rune tutor is later content that does not exist in
  this era. Do not look again.

## Income, since runes cost gold

- **Pickpocketing** at Thieving 85 yields **3 coins** per success at ~64%,
  about **900 gp/hour**, from Lumbridge Men and Women. No market stalls were
  found in Lumbridge or near the border; stalls would be `interactLoc` with a
  "Steal-from" option rather than `interactNpc`, so an NPC-only sweep would
  miss them, and Varrock's market is unexplored.
- **The forum returns no replies**, and `hiscores` shows no character training
  Magic other than ours. Asking other players is not a route to anything.
- A **Staff of air** removes the Air rune from every Strike cast permanently.
  Outside lore puts it at Zaff's in Varrock for ~1,000 gp; not yet verified
  here, and worth checking now that Varrock is reachable.
