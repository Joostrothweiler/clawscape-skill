// A thief: turns time into coins, and coins are what the scorer's burst is
// bought with.
//
// The ladder reads top to bottom and the order is a claim about priority, not
// about value. Only the `steal_target` group is the learner's to permute: which
// townsperson to rob was always a guess. That an unblocking rule outranks an
// earning rule is a judgement, and no measured reward should be able to
// overturn it -- a fleet that learns to ignore a blocking modal earns nothing
// at all, very efficiently.

import type { Mind, Role, Rule } from '../types.js';
import { prelude } from './prelude.js';

/** Open ground east of Lumbridge castle. The men inside are not routable. */
export const MEN = { x: 3231, z: 3218 };

/** %stunned in pickpocket.rs2; further interactions are dropped server-side. */
const STUN_TICKS = 8;

/** Stop thieving at or below this, and do not resume until back up to REST_UNTIL. */
const REST_BELOW = 4;
const REST_UNTIL = 9;

/**
 * Tiles a character has just handed off on, and must not re-take from.
 *
 * A dropped pile stays visible to whoever dropped it, so without this a
 * preparer drops its purse for the scorer and immediately picks it straight
 * back up -- a hand-off that never happens, at full speed, looking healthy on
 * every counter. Keyed `character -> "x,z" -> tick it becomes fair game again`.
 */
const handedOff = new Map<string, Map<string, number>>();

function markHandoff(who: string, x: number, z: number, tick: number): void {
    const mine = handedOff.get(who) ?? new Map<string, number>();
    mine.set(`${x},${z}`, tick + HANDOFF_BLIND_TICKS);
    handedOff.set(who, mine);
}

/** True when this pile is one we may take: it exists, and it is not our own hand-off. */
function theirs(who: string, tick: number, pile: { x: number; z: number } | null): boolean {
    if (!pile) return false;
    const until = handedOff.get(who)?.get(`${pile.x},${pile.z}`);
    return until === undefined || tick >= until;
}

/** Roughly how long a drop stays private to the dropper, with margin. */
const HANDOFF_BLIND_TICKS = 400;

const rules: Rule[] = [
    ...prelude,
    {
        // A failed pickpocket costs a hitpoint and there is no food in reach,
        // so a thief that never stops is a thief that dies -- and death
        // scatters the coins the whole plan is funded by.
        //
        // Ungrouped, and above the earning rules, on purpose. This is a
        // judgement about priority, not a guess about value, so the learner is
        // not allowed to reorder it. Measured reward would demote it every
        // time: resting pays literally nothing per second, right up until the
        // run it saves.
        name: 'rest_when_hurt',
        when: b => b.hp <= REST_BELOW,
        then: b => ({
            action: { type: 'wait', ticks: 4, reason: `resting at ${b.hp}hp` },
            done: after => after.hp >= REST_UNTIL,
            // Regeneration is slow, so this deliberately holds the character
            // for a long time rather than re-deciding every few ticks.
            ticks: 400
        })
    },
    {
        // Coins on the floor are either ours or a teammate's hand-off. Either
        // way they are free, and worth more than another attempt.
        name: 'take_loose_coins',
        when: b => b.free > 0 && theirs(b.name, b.tick, b.ground(/^coins$/i)),
        then: b => {
            const pile = b.ground(/^coins$/i)!;
            const before = b.coins;
            return {
                action: { type: 'pickupItem', x: pile.x, z: pile.z, itemId: pile.id, reason: 'loose gold' },
                done: after => after.coins > before,
                ticks: 6
            };
        }
    },
    {
        name: 'steal_from_a_man',
        group: 'steal_target',
        when: b => b.npc(/^man$/i, /pickpocket/i) !== null,
        then: b => {
            const target = b.npc(/^man$/i, /pickpocket/i)!;
            const before = b.coins;
            const hp = b.hp;
            return {
                action: {
                    type: 'interactNpc',
                    npcIndex: target.index,
                    optionIndex: target.op,
                    reason: 'pickpocket'
                },
                // Either outcome is evidence the attempt resolved: coins for a
                // success, a lost hitpoint for the stun. Waiting only on coins
                // would score every failure as a timeout and inflate its cost.
                done: after => after.coins > before || after.hp < hp,
                ticks: 6,
                cooldown: STUN_TICKS
            };
        }
    },
    {
        name: 'steal_from_a_woman',
        group: 'steal_target',
        when: b => b.npc(/^woman$/i, /pickpocket/i) !== null,
        then: b => {
            const target = b.npc(/^woman$/i, /pickpocket/i)!;
            const before = b.coins;
            const hp = b.hp;
            return {
                action: {
                    type: 'interactNpc',
                    npcIndex: target.index,
                    optionIndex: target.op,
                    reason: 'pickpocket'
                },
                done: after => after.coins > before || after.hp < hp,
                ticks: 6,
                cooldown: STUN_TICKS
            };
        }
    },
    {
        // Last rung: nothing to rob within view, so go where the work is.
        name: 'return_to_station',
        when: () => true,
        then: b => ({
            action: { type: 'walkTo', x: MEN.x, z: MEN.z, running: true, reason: 'return to station' },
            done: after => after.at(MEN.x, MEN.z, 6),
            ticks: 30
        })
    }
];

/** A preparer carrying at least this much makes a hand-off run. */
const HANDOFF_AT = 60;

/**
 * Concentrate the fleet's gold in one character.
 *
 * Under a peak metric the fleet's score is whatever one character can convert
 * in fifteen seconds, so gold spread thinly across five pockets is worth much
 * less than the same gold in one. These two rules are the whole of the
 * collaboration: preparers walk their takings to the scorer and drop them, and
 * `take_loose_coins` -- which every character already has -- picks them up.
 *
 * The hand-off is a drop rather than a trade because a drop is one op and a
 * trade is an interface negotiation across two clients. The cost is latency:
 * a dropped pile is private to the dropper for about a minute before anyone
 * else can see it, so this concentrates gold on a delay rather than instantly.
 */
function handoff(scorer: string): Rule[] {
    return [
        {
            name: 'carry_takings_to_the_scorer',
            when: b => b.role === 'preparer' && b.coins >= HANDOFF_AT && !b.at(MEN.x, MEN.z, 3),
            then: () => ({
                action: { type: 'walkTo', x: MEN.x, z: MEN.z, running: true, reason: `hand-off to ${scorer}` },
                done: after => after.at(MEN.x, MEN.z, 3),
                ticks: 30
            })
        },
        {
            name: 'drop_takings_for_the_scorer',
            when: b => b.role === 'preparer' && b.coins >= HANDOFF_AT && b.at(MEN.x, MEN.z, 3),
            then: b => {
                const purse = b.item(/^coins$/i);
                if (!purse) return null;
                const before = b.coins;
                const x = b.state.player!.worldX;
                const z = b.state.player!.worldZ;
                markHandoff(b.name, x, z, b.tick);
                return {
                    action: { type: 'dropItem', slot: purse.slot, reason: `hand-off to ${scorer}` },
                    done: after => after.coins < before,
                    ticks: 5
                };
            }
        }
    ];
}

export function thief(name: string, role: Role = 'preparer', scorer = name): Mind {
    // The hand-off sits directly below picking things up -- so below survival
    // too -- and above the earning rules: a full purse is worth delivering
    // before stealing more, but never worth dying for. Anchored by name
    // rather than by index, because the ladder above it grows.
    const anchor = rules.findIndex(r => r.name === 'take_loose_coins');
    if (anchor === -1) throw new Error('thief ladder lost its take_loose_coins anchor');
    const composed = [...rules.slice(0, anchor + 1), ...handoff(scorer), ...rules.slice(anchor + 1)];
    return { name, role, rules: composed };
}
