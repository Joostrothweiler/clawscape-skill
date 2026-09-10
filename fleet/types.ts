// The vocabulary the whole fleet is written in.
//
// One idea holds the layer together: a rule proposes a single Intent, and the
// kernel does not consider another rule until that Intent has *observably*
// resolved. Everything else -- learning, collaboration, reporting -- reads the
// stream of resolved Intents. That is the seam our previous attempt lacked,
// where "the action was dispatched" and "the action happened" were the same
// event and every measurement downstream inherited the confusion.

import type { BotAction, BotWorldState } from '#/bot/types.js';

/** What a character is for. The fleet's score comes from one of them. */
export type Role = 'scorer' | 'preparer';

/**
 * A single dispatch plus the evidence that would prove it worked.
 *
 * `done` is the whole point. The engine refuses ops it will not run and answers
 * with UNSET_MAP_FLAG and nothing else, so "the packet was written" tells you
 * almost nothing. A rule that cannot say what success would look like is a rule
 * whose reward cannot be measured, and it has no business in a learner.
 */
export interface Intent {
    action: BotAction;
    /** True once the world shows the action landed. */
    done?: (b: Beliefs) => boolean;
    /** Give up after this many ticks and record a timeout. */
    ticks?: number;
    /** Ticks to sit still after resolution (stun, animation, respawn). */
    cooldown?: number;
    /**
     * Called once when this Intent resolves, with how it ended.
     *
     * The hook a rule needs to learn something a reward cannot express: which
     * particular target just refused it. A value estimate says "picking things
     * up is worth 0/s"; it cannot say "that pile, specifically, is not yours".
     */
    onResolve?(resolution: Resolution, b: Beliefs): void;
}

/**
 * One rung of the ladder.
 *
 * `group` marks rules that are alternatives for the same job -- which man to
 * rob, which tree to fell. Only those are ever reordered by the learner; an
 * ungrouped rule keeps the position a person gave it, which is what stops a
 * measured reward from ever demoting "eat before you die".
 */
export interface Rule {
    name: string;
    group?: string;
    when: (b: Beliefs) => boolean;
    then: (b: Beliefs) => Intent | null;
}

export interface Mind {
    name: string;
    role: Role;
    /** Priority order. First match wins; the learner may permute within groups. */
    rules: Rule[];
}

/** How an Intent ended. Anything but `done` earned nothing. */
export type Resolution =
    | 'done' // the evidence arrived
    | 'rejected' // the server refused the op
    | 'timeout' // nothing observable happened in time
    | 'blocked'; // a rule proposed nothing runnable

/** One row of the training set. Append-only, one JSON object per line. */
export interface Outcome {
    t: number;
    character: string;
    role: Role;
    rule: string;
    group?: string;
    resolution: Resolution;
    /** Ticks from dispatch to resolution. The denominator of every rate. */
    ticks: number;
    ms: number;
    /** Experience this character gained while the Intent was in flight. */
    xp: number;
    /** Per-skill breakdown, so a learner can score one skill at a time. */
    xpBySkill?: Record<string, number>;
    coins: number;
}

export interface Target {
    index: number;
    name: string;
    distance: number;
    /** The matched option's opIndex, straight off the target. */
    op: number;
}

export interface Placed {
    x: number;
    z: number;
    id: number;
    name: string;
    distance: number;
    op: number;
}

/**
 * A read-only view of the world, computed once per tick and handed to every
 * predicate. Rules never touch the client: they answer questions about
 * Beliefs and return an Intent, which makes them pure, cheap and testable
 * without a game server.
 */
export interface Beliefs {
    readonly name: string;
    readonly role: Role;
    readonly tick: number;
    readonly state: BotWorldState;

    readonly hp: number;
    readonly maxHp: number;
    readonly coins: number;
    readonly free: number;

    level(skill: string): number;
    xp(skill: string): number;
    /** Total quantity across every stack, not the first slot. */
    count(pattern: RegExp): number;
    item(pattern: RegExp): { slot: number; name: string; count: number } | null;

    /**
     * Nearest matching target that local routing believes it can reach.
     *
     * `op` is the matched option's own `opIndex`, read off the target rather
     * than assumed. Option ordering is not stable -- skill dialogs publish four
     * buttons per product, and arrow shafts are option 4 of 12, not option 1 --
     * so a hardcoded index is a silent no-op waiting to happen.
     */
    npc(pattern: RegExp, option?: RegExp): Target | null;
    loc(pattern: RegExp, option?: RegExp): Placed | null;
    ground(pattern: RegExp): Placed | null;

    readonly dialogOpen: boolean;
    /** True while a dialog is mid-animation and will not accept a click yet. */
    readonly dialogWaiting: boolean;
    readonly dialogOptions: ReadonlyArray<{ index: number; text: string }>;
    readonly modalOpen: boolean;
    /** Which modal, so a rule can recognise one rather than blindly closing it. */
    readonly modalInterface: number;
    readonly inCombat: boolean;
    at(x: number, z: number, within?: number): boolean;
}
