// The training set, and the score.
//
// Every resolved Intent becomes one line here. It is the only thing the learner
// reads, the only thing the report reads, and the only durable record that a
// run happened -- so it is written eagerly rather than at shutdown, because the
// runs worth learning from are disproportionately the ones that ended badly.

import { appendFileSync, readFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { Outcome } from './types.js';

export const MEMORY = process.env.FLEET_MEMORY ?? join(import.meta.dir, 'memory.jsonl');

/** Buffered append. One fsync per tick across a fleet would dominate the loop. */
const pending: string[] = [];

export function remember(row: Outcome): void {
    pending.push(JSON.stringify(row));
    if (pending.length >= 32) flush();
}

export function flush(): void {
    if (!pending.length) return;
    mkdirSync(dirname(MEMORY), { recursive: true });
    appendFileSync(MEMORY, pending.join('\n') + '\n');
    pending.length = 0;
}

export function load(path = MEMORY): Outcome[] {
    if (!existsSync(path)) return [];
    const out: Outcome[] = [];
    for (const line of readFileSync(path, 'utf8').split('\n')) {
        if (!line.trim()) continue;
        try {
            out.push(JSON.parse(line) as Outcome);
        } catch {
            // A half-written final line is normal after a kill. Skip it.
        }
    }
    return out;
}

/**
 * The benchmark's metric: the most experience the fleet gained in any window
 * of `windowMs`, not the total and not the average.
 *
 * This distinction is the whole strategy. RuneBench scores the best 15-second
 * window explicitly to "reward agents that discover higher-level strategies,
 * beyond pure time-on-task", and published runs show a median peak-to-mean
 * ratio around 12x with the best near 100x. Under a peak metric, every second
 * spent stockpiling is free, and the fleet's job is to arrive at one moment
 * holding everything needed to convert inputs into experience as fast as the
 * server will accept the clicks.
 *
 * Measuring it fleet-wide rather than per character is deliberate: it is the
 * quantity we actually want to maximise, and it is what makes four characters
 * feeding a fifth a rational thing for a learner to discover.
 */
export function peakWindow(rows: Outcome[], windowMs = 15_000): { xp: number; at: number; window: Outcome[] } {
    const gains = rows.filter(r => r.xp > 0).sort((a, b) => a.t - b.t);
    let best = { xp: 0, at: 0, window: [] as Outcome[] };
    let left = 0;
    let sum = 0;
    for (let right = 0; right < gains.length; right++) {
        sum += gains[right]!.xp;
        while (gains[right]!.t - gains[left]!.t > windowMs) {
            sum -= gains[left]!.xp;
            left++;
        }
        if (sum > best.xp) best = { xp: sum, at: gains[left]!.t, window: gains.slice(left, right + 1) };
    }
    return best;
}

/** Sustained rate, for contrast with the peak. Both numbers matter to us. */
export function meanXpPerWindow(rows: Outcome[], windowMs = 15_000): number {
    if (rows.length < 2) return 0;
    const first = Math.min(...rows.map(r => r.t));
    const last = Math.max(...rows.map(r => r.t));
    const span = Math.max(1, last - first);
    return (rows.reduce((a, r) => a + r.xp, 0) * windowMs) / span;
}
