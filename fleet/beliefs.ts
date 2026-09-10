// Beliefs: one cheap, read-only view of the world per tick.
//
// Rules ask questions here and nowhere else. Keeping predicates away from the
// client is what makes a ladder testable without a game server, and it removes
// a whole class of bug where two rules in the same tick disagree about the
// world because one of them re-read it.

import type { BotWorldState, NearbyNpc, NearbyLoc, GroundItem } from '#/bot/types.js';
import type { Beliefs, Role } from './types.js';

/**
 * Prefer a target local routing believes it can reach.
 *
 * The client pathfinds before every interaction and, when it cannot route,
 * returns without writing a packet -- so the server never answers "I can't
 * reach that!" either. An unreachable target is therefore not a failed action
 * but a silent no-op, which reads to a learner as an action that took time and
 * paid nothing. Filtering here is what keeps that noise out of the training
 * set. `reachable === undefined` means the client did not say, so we allow it.
 */
function reachableFirst<T extends { reachable?: boolean; distance: number }>(all: T[]): T | null {
    let best: T | null = null;
    for (const c of all) {
        if (c.reachable === false) continue;
        if (!best || c.distance < best.distance) best = c;
    }
    return best;
}

/**
 * The opIndex of the option we actually want, read off the target.
 *
 * Returns null when the target does not offer it, which is the difference
 * between "no such man" and "a man with no Pickpocket option" -- and only the
 * second is worth walking to.
 */
function optionIndex(options: { text: string; opIndex: number }[] | undefined, want?: RegExp): number | null {
    if (!want) return 1;
    return (options ?? []).find(o => want.test(o.text))?.opIndex ?? null;
}

export function beliefs(name: string, role: Role, tick: number, state: BotWorldState): Beliefs {
    const player = state.player;
    const skills = new Map(state.skills.map(s => [s.name.toLowerCase(), s]));

    const count = (pattern: RegExp): number =>
        state.inventory.filter(i => pattern.test(i.name)).reduce((a, i) => a + i.count, 0);

    return {
        name,
        role,
        tick,
        state,

        hp: player?.hp ?? 0,
        maxHp: player?.maxHp ?? 0,
        coins: count(/^coins$/i),
        // 28 slots; length is occupied slots, not total quantity.
        free: 28 - state.inventory.length,

        level: (skill: string) => skills.get(skill.toLowerCase())?.level ?? 0,
        xp: (skill: string) => skills.get(skill.toLowerCase())?.experience ?? 0,
        count,
        item: (pattern: RegExp) => {
            const hit = state.inventory.find(i => pattern.test(i.name));
            return hit ? { slot: hit.slot, name: hit.name, count: hit.count } : null;
        },

        npc: (pattern: RegExp, option?: RegExp) => {
            const hits = state.nearbyNpcs.filter(
                (n: NearbyNpc) => pattern.test(n.name) && optionIndex(n.optionsWithIndex, option) !== null
            );
            const best = reachableFirst(hits);
            if (!best) return null;
            return {
                index: best.index,
                name: best.name,
                distance: best.distance,
                op: optionIndex(best.optionsWithIndex, option)!
            };
        },
        loc: (pattern: RegExp, option?: RegExp) => {
            const hits = state.nearbyLocs.filter(
                (l: NearbyLoc) => pattern.test(l.name) && optionIndex(l.optionsWithIndex, option) !== null
            );
            const best = reachableFirst(hits);
            if (!best) return null;
            return {
                x: best.x,
                z: best.z,
                id: best.id,
                name: best.name,
                distance: best.distance,
                op: optionIndex(best.optionsWithIndex, option)!
            };
        },
        ground: (pattern: RegExp) => {
            const hits = state.groundItems.filter((g: GroundItem) => pattern.test(g.name));
            const best = reachableFirst(hits);
            if (!best) return null;
            return { x: best.x, z: best.z, id: best.id, name: best.name, distance: best.distance, op: 1 };
        },

        dialogOpen: Boolean(state.dialog?.isOpen),
        dialogWaiting: Boolean(state.dialog?.isWaiting),
        dialogOptions: state.dialog?.options ?? [],
        modalOpen: Boolean(state.modalOpen),
        modalInterface: state.modalInterface ?? -1,
        inCombat: Boolean(player?.combat?.inCombat),
        at: (x: number, z: number, within = 2) =>
            !!player && Math.abs(player.worldX - x) <= within && Math.abs(player.worldZ - z) <= within
    };
}

/** Total experience across every skill. The fleet's raw score input. */
export function totalXp(state: BotWorldState): number {
    return state.skills.reduce((a, s) => a + s.experience, 0);
}

export function xpBySkill(state: BotWorldState): Record<string, number> {
    const out: Record<string, number> = {};
    for (const s of state.skills) out[s.name] = s.experience;
    return out;
}
