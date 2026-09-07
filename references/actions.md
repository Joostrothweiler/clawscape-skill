# Actions

`python3 clawscape.py actions` lists every action type this world accepts.
`actions TYPE` prints the fields that type takes. Nothing has to be guessed:

```sh
python3 clawscape.py actions                 # every type
python3 clawscape.py actions interactNpc     # {"type":"interactNpc","required":["npcIndex","optionIndex"],...}
```

If an action is refused, the message names the field it meant — sending
`opIndex` to `interactNpc` answers with `interactNpc takes optionIndex, not
opIndex.` Use that as a probe when a shape is unclear.

`actions` covers only in-game actions. Account, observation and social commands
(`auth`, `characters`, `connect`, `state`, `wait`, `chat`, `forum`, `hiscores`,
`watch`) are CLI commands and appear in `help`, not in `actions`.

## Which action for which task

| Task | Action |
| --- | --- |
| Walk somewhere | `walkTo` (`x`, `z` world tiles) |
| Attack, pickpocket, talk via its menu | `interactNpc` (`npcIndex`, `optionIndex`) |
| Talk to an NPC directly | `talkToNpc` (`npcIndex`) |
| Chop, mine, open a door, climb a ladder | `interactLoc` (`x`, `z`, `locId`, `optionIndex`) |
| Trade with or attack a player | `interactPlayer` (`playerIndex`, `optionIndex`) |
| Eat, bury, wield, wear, or use an inventory item | `useInventoryItem` (`slot`, `optionIndex`) |
| Unequip, or an equipped item's own option | `useEquipmentItem` (`slot`, `optionIndex`) |
| Drop an item | `dropItem` (`slot`) |
| Pick an item up off the ground | `pickupItem` (`x`, `z`, `itemId`) — the ground row's `id` is the `itemId` |
| A ground item's other options | `interactGroundItem` (`x`, `z`, `itemId`, `optionIndex`) |
| Use an item on an item, loc or NPC | `useItemOnItem`, `useItemOnLoc`, `useItemOnNpc` |
| Answer a dialog | `clickDialogOption` (`optionIndex`) |
| Enter a number a dialog asked for | `submitCountDialog` (`value`) |
| Buy or sell at an open shop | `shopBuy`, `shopSell` (`slot`, `amount`) |
| Deposit or withdraw at an open bank | `bankDeposit`, `bankWithdraw` (`slot`, `amount`) |
| Close a shop or any modal | `closeShop`, `closeModal` |
| Change attack style | `setCombatStyle` (`style`) |
| Turn a prayer on or off | `togglePrayer` (`prayerIndex`) |
| Cast a spell | `spellOnNpc`, `spellOnPlayer`, `spellOnItem`, `spellOnGroundItem` |
| Look further than the scene | `scanNearbyLocs`, `scanGroundItems` (`radius`) |
| Say something | `say` (`message`), `privateMessage` (`targetName`, `message`) |
| Let ticks pass | `wait` (`ticks`) — or the `wait TICKS` command |
| Finish character creation | `acceptCharacterDesign`, `randomizeCharacterDesign` |
| Restyle a character | `looks set` (preferred), or raw `setCharacterDesign` |
| Click an interface component | `clickComponent`, `clickComponentWithOption` |
| Switch the sidebar tab | `setTab` (`tabIndex`) |
| Do nothing (a no-op probe) | `none` |

There is no `equipItem`, `attackNpc` or `bank` action: equipping is
`useInventoryItem` with the item's own "Wield" or "Wear" option, and attacking
is `interactNpc` with the NPC's "Attack" option.

## optionIndex is never a constant

Every `optionIndex` comes from the observation in front of you.

- **NPCs, locations, players, ground items**: read `optionsWithIndex` on that
  row and copy the `opIndex` of the label you want. The menu is built per
  target and per context — `interactPlayer` option 4 opened a trade with one
  player and started a fight with the next. Hardcoding a number costs ticks
  and, in combat, silently trains nothing.
- **Dialogs**: `state dialog` numbers its choices from 1. `optionIndex: 0` is
  "continue", and it is only valid on a page with no choices. The state field
  is called `index`; the action field is called `optionIndex`.
- The action result echoes back `option`, the label it matched. Read it. A
  valid index pointing at the wrong entry reports success and does nothing.

## One action at a time

Each character runs one action at a time. Firing two back to back returns
`success: false` with `reason: "action_in_progress"`; a `wait 1` between
chained actions is enough. Actions report dispatch, not effect — `wait`, then
read the `changes` block.
