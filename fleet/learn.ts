// Rank the interchangeable rules by what they actually paid.
//
//   bun src/fleet/learn.ts [--explain] [--dry-run]
//
// A plain multi-armed bandit: rules sharing a `group` are the arms, the reward
// is what the kernel recorded, and the policy is the order they sit in. Two
// design choices here are corrections to a previous version of this idea that
// failed in specific, instructive ways.
//
// **Credit is causal.** Value is computed from the acting character's own
// gains and nothing else. An earlier attempt scored actions against a
// fleet-wide potential, on the theory that a fleet with one shared goal should
// share one reward. Measured live, a character whose rule found no target and
// did nothing for eleven seconds scored +269/s, because two other characters
// were working through those same seconds. It stalled, and the learner
// promoted the rule that stalled it. A shared reward pays every agent for the
// fleet's progress, so standing still scores as well as working -- the lazy
// agent problem, arrived at the expensive way. Cross-character enabling is
// real and it is handled by reward-to-go below, which follows one character's
// own timeline.
//
// **Failure is evidence, not absence.** A rejected or timed-out action counts
// as a trial and contributes zero reward against the time it burned. The
// earlier version only counted successes, so a rule that failed structurally
// -- no such NPC here, ever -- stayed permanently "unmeasured", and optimistic
// initialisation kept promoting it to the top of the ladder forever. Trying an
// unknown arm first is right; never noticing that it does not work is not.

import { load, peakWindow } from './memory.js';
import { loadPolicy, savePolicy, type Policy } from './policy.js';
import type { Outcome } from './types.js';

interface Args {
    explain: boolean;
    dryRun: boolean;
    coinWeight: number;
    halfLife: number;
    epsilon: number;
    minTrials: number;
    lookahead: number;
    gamma: number;
    horizon: number;
}

export interface Arm {
    rule: string;
    group: string;
    value: number;
    trials: number;
    failures: number;
    xp: number;
    seconds: number;
}

/**
 * Discounted experience the SAME character earned after this action.
 *
 * This is the Monte-Carlo return, and it is what connects an action to
 * consequences that arrive later: walking to the men pays nothing at the
 * moment it resolves, and everything afterwards depends on it. Kept to one
 * character's own timeline on purpose -- widening it to the fleet is exactly
 * the cross-attribution that produced the lazy agent.
 */
function rewardToGo(rows: Outcome[], gamma: number, horizon: number): Map<Outcome, number> {
    const byCharacter = new Map<string, Outcome[]>();
    for (const row of rows) {
        const list = byCharacter.get(row.character) ?? [];
        list.push(row);
        byCharacter.set(row.character, list);
    }
    const future = new Map<Outcome, number>();
    for (const list of byCharacter.values()) {
        list.sort((a, b) => a.t - b.t);
        for (let i = 0; i < list.length; i++) {
            let sum = 0;
            const base = list[i]!.t;
            for (const later of list.slice(i + 1, i + 1 + horizon)) {
                sum += later.xp * gamma ** ((later.t - base) / 1000);
            }
            future.set(list[i]!, sum);
        }
    }
    return future;
}

export function rank(rows: Outcome[], args: Args): Arm[] {
    const grouped = rows.filter(r => r.group);
    const future = rewardToGo(rows, args.gamma, args.horizon);
    const now = grouped.length ? Math.max(...grouped.map(r => r.t)) : Date.now();

    const acc = new Map<string, Arm & { reward: number; weight: number }>();
    for (const row of grouped) {
        const key = `${row.group}/${row.rule}`;
        const arm = acc.get(key) ?? {
            rule: row.rule,
            group: row.group!,
            value: 0,
            trials: 0,
            failures: 0,
            xp: 0,
            seconds: 0,
            reward: 0,
            weight: 0
        };
        // The world moves -- a spawn wanders off, a shelf empties -- so recent
        // evidence outweighs old, and an all-time average would keep
        // recommending a target that is no longer there.
        const age = Math.max(0, now - row.t) / 1000;
        const recency = args.halfLife > 0 ? 0.5 ** (age / args.halfLife) : 1;
        const gain = row.xp + row.coins * args.coinWeight + (future.get(row) ?? 0) * args.lookahead;

        arm.reward += gain * recency;
        // Seconds are counted whatever the outcome. A rule that burns six
        // ticks being refused is not free, and this is where that shows up.
        arm.seconds += Math.max(0.1, row.ms / 1000) * recency;
        arm.trials += 1;
        if (row.resolution !== 'done') arm.failures += 1;
        arm.xp += row.xp;
        acc.set(key, arm);
    }

    const arms = [...acc.values()].map(a => ({
        rule: a.rule,
        group: a.group,
        value: a.seconds > 0 ? a.reward / a.seconds : 0,
        trials: a.trials,
        failures: a.failures,
        xp: a.xp,
        seconds: Math.round(a.seconds)
    }));
    return arms.sort((x, y) => y.value - x.value);
}

export function decide(arms: Arm[], args: Args): { policy: Policy; explored: string[] } {
    const groups = new Map<string, Arm[]>();
    for (const arm of arms) {
        const list = groups.get(arm.group) ?? [];
        list.push(arm);
        groups.set(arm.group, list);
    }
    const policy: Policy = {};
    const explored: string[] = [];
    for (const [group, members] of groups) {
        // With probability epsilon, shuffle instead of rank. A world that
        // changes makes yesterday's best arm wrong, and an agent that never
        // explores never finds out.
        if (Math.random() < args.epsilon) {
            explored.push(group);
            policy[group] = [...members].sort(() => Math.random() - 0.5).map(a => a.rule);
            continue;
        }
        policy[group] = [...members]
            .sort((a, b) => {
                // Under-sampled arms first, so everything is tried before
                // anything is judged -- but they are still *listed*, so an arm
                // that keeps failing accrues trials and stops being exempt.
                const au = a.trials < args.minTrials ? 1 : 0;
                const bu = b.trials < args.minTrials ? 1 : 0;
                if (au !== bu) return bu - au;
                return b.value - a.value;
            })
            .map(a => a.rule);
    }
    return { policy, explored };
}

if (import.meta.main) {
    const argv = process.argv.slice(2);
    const num = (flag: string, fallback: number): number =>
        Number(argv.find(a => a.startsWith(`--${flag}=`))?.split('=')[1] ?? fallback);
    const args: Args = {
        explain: argv.includes('--explain'),
        dryRun: argv.includes('--dry-run'),
        coinWeight: num('coin-weight', 1),
        halfLife: num('half-life', 3600),
        epsilon: num('epsilon', 0.2),
        minTrials: num('min-trials', 5),
        lookahead: num('lookahead', 0.3),
        gamma: num('gamma', 0.995),
        horizon: num('horizon', 15)
    };

    const rows = load();
    if (!rows.length) {
        console.error('[learn] no memory yet -- run the fleet first');
        process.exit(1);
    }
    const arms = rank(rows, args);
    const { policy, explored } = decide(arms, args);
    const before = loadPolicy();

    if (args.explain) {
        const peak = peakWindow(rows);
        console.log(
            `[learn] ${rows.length} actions, ${new Set(rows.map(r => r.character)).size} characters, ` +
                `peak ${peak.xp} xp/15s\n`
        );
        console.log('rule'.padEnd(24) + 'value/s'.padStart(9) + 'trials'.padStart(8) + 'fail%'.padStart(7) + '   xp');
        for (const a of arms) {
            const failRate = a.trials ? Math.round((a.failures / a.trials) * 100) : 0;
            console.log(
                a.rule.padEnd(24) +
                    a.value.toFixed(1).padStart(9) +
                    String(a.trials).padStart(8) +
                    `${failRate}%`.padStart(7) +
                    `   ${a.xp}`
            );
        }
        for (const group of explored) console.log(`\n[learn] ${group}: exploring (shuffled)`);
        console.log('\n[learn] order:', JSON.stringify(policy));
    }

    const changed = JSON.stringify(before) !== JSON.stringify(policy);
    if (changed && !args.dryRun) savePolicy(policy);
    console.log(`[learn] ${changed ? (args.dryRun ? 'would change' : 'wrote') : 'unchanged'} policy`);
}
