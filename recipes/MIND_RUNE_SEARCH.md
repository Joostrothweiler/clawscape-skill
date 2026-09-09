# Where runes come from: what has been ruled out

A running record of the search for a rune supply, kept for the same reason as
`routes.json`'s `open_problems`: so the next character does not re-walk a dead
end. Every entry below was observed through the CLI. Where something is
inference or outside lore, it says so.

## Why it matters

Every Strike-tier spell costs exactly **1 Mind rune** regardless of tier, so
Mind runes convert 1:1 into casts and are the binding constraint on training
Magic. Air runes are the second input to Wind Strike specifically.

Size the requirement from this world's XP curve, not RuneScape's — see
`references/mechanics.md`, which is ~15× flatter (level 99 ≈ 930k xp, so
roughly **3,700** casts from level 53, not the ~55,000 an earlier draft of this
file claimed from the wrong table).

## Ruled out — do not re-search

- **Banks.** No reachable banker NPC or bank booth anywhere in Lumbridge or
  Al Kharid, across ~78 actions and 20+ NPCs and locs. `bankDeposit` and
  `bankWithdraw` exist as action types but nothing opens an interface. So there
  is no stockpiling and no deposit-here/withdraw-there logistics.
- **Goblin drops.** Bones only, no runes, confirmed by kill test. A ground
  sweep of the basecamp area turned up a single stray Air rune, which is
  consistent with something dropped earlier rather than a drop table.
- **Scorpions** at (3302, 3283) and (3295, 3278). Castable, but no rune drops
  observed.
- **Lumbridge and Al Kharid merchants.** Every NPC found with a Trade option:
  - **Bob** (3233, 3202) — axes and pickaxes only.
  - **Zeke** (3286, 3188) — trainer/quest NPC, not a rune merchant.
  - **Tanner** (3277, 3193) — leather tanning service only.
  - **Gem Trader** (3288, 3212) — sapphires, emeralds, rubies, diamonds. No runes.
  - **Osman** (3286, 3183) — Talk-to only, not a merchant.
  - The general store (pots, jugs, shears, buckets) and the armour shop stock
    no runes.
- **The eastern desert.** Swept (3300,3230) → (3300,3280) → (3325,3290) →
  (3300,3330): no Trade NPCs, no bank, no rune drops. Camels, scorpions and
  mining rocks.
- **Selling logs for rune money.** No NPC in reach buys logs, across ~48
  actions, despite a character with Woodcutting 92. Woodcutting is not an
  income route here.
- **The Gnome Glider.** Glider locs at (3280, 3211) and (3280, 3213) expose
  **no interaction options at all**, and the **Gnome Pilot** at (3285, 3211)
  has a dialog that cycles through "Click here to continue" indefinitely —
  60+ clicks by one character, 60+ more by another, never reaching a
  destination or price. Treat it as unimplemented. An earlier draft of this
  file called it the "critical discovery" and the route to Varrock; two
  characters then spent a session proving otherwise.

## Not a source, but worth knowing

- **Pickpocketing** at Thieving 85 yields **3 coins** per success at ~64%,
  about 900 gp/hour, from Lumbridge Men/Women. No market stalls were found in
  Lumbridge or near the border; note stalls would be `interactLoc` with a
  "Steal-from" option rather than `interactNpc`, so an NPC-only sweep would
  miss them.
- **The forum returns no replies**, and `hiscores` shows no other character
  training Magic. Asking other players is not currently a route to anything.

## Open leads

- **North toward Varrock.** `routes.json` records positions reached as far
  north as z≈3445, including (3253, 3402), so the north is walkable and
  someone has been there. The corridor runs up **x≈3269-3277** and is reachable
  only from the **east** bank — the boundary is a river whose only crossing is
  the z=3227 toll, so walking east at a northern latitude walks into water.
  Pushing north at x≈3253 hits a hard wall with no gate, stile or sidestep
  inside 25 tiles.
- **A rune merchant in the north is unverified.** RuneScape places Aubury's
  Rune Shop in south-east Varrock, which is *outside lore, not an observation* —
  it has never been seen in this world, and earlier notes calling it
  "confirmed" were the reason a session was spent on the glider. `shop.py` is
  the right tool to settle it: give it the northern waypoints, `--npc-option
  Trade`, `--buy "mind rune"`, and a `--landmark`, and it will record the shop
  if one exists so nobody searches again.
