// The learned half of a ladder, kept separate from the written half.
//
// Rules are code: they typecheck, a person reviews them, and their priority is
// a judgement. What the learner is allowed to change is narrower -- the order
// of rules inside a `group`, which were alternatives for the same job and
// whose ordering was always a guess. Keeping that in a small JSON file means
// the policy can be read, diffed, hand-edited and reverted, and it means an
// experiment can be reproduced by checking out one file.
//
// Anything ungrouped keeps the position it was written in. That is what stops
// a measured reward from ever demoting "get out of the blocking dialog".

import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Mind, Rule } from './types.js';

export const POLICY = process.env.FLEET_POLICY ?? join(import.meta.dir, 'policy.json');

/** group -> rule names, best first. */
export type Policy = Record<string, string[]>;

export function loadPolicy(path = POLICY): Policy {
    if (!existsSync(path)) return {};
    try {
        return JSON.parse(readFileSync(path, 'utf8')) as Policy;
    } catch {
        return {};
    }
}

export function savePolicy(policy: Policy, path = POLICY): void {
    writeFileSync(path, JSON.stringify(policy, null, 2) + '\n');
}

/**
 * Permute grouped rules into the learned order, leaving every slot where it is.
 *
 * The group's *positions* in the ladder are fixed; only which rule sits in
 * which of those positions changes. A group whose members straddle an
 * ungrouped safety rule therefore cannot reorder across it.
 */
export function applyPolicy(mind: Mind, policy: Policy): Mind {
    const slots = new Map<string, number[]>();
    mind.rules.forEach((rule, index) => {
        if (!rule.group) return;
        const list = slots.get(rule.group) ?? [];
        list.push(index);
        slots.set(rule.group, list);
    });

    const rules: Rule[] = [...mind.rules];
    for (const [group, positions] of slots) {
        const order = policy[group];
        if (!order?.length) continue;
        const members = positions.map(i => mind.rules[i]!);
        const ranked = [...members].sort((a, b) => {
            const ai = order.indexOf(a.name);
            const bi = order.indexOf(b.name);
            // A rule the policy has never heard of is unmeasured, and an
            // unmeasured arm goes first: try everything before judging
            // anything.
            return (ai === -1 ? -1 : ai) - (bi === -1 ? -1 : bi);
        });
        positions.forEach((slot, k) => {
            rules[slot] = ranked[k]!;
        });
    }
    return { ...mind, rules };
}
