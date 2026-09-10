// Run the fleet: N characters, one process, one tick loop each.
//
//   cd server/webclient
//   bun src/fleet/run.ts sylas gorruk morgra oakward thrain [--minutes=N]
//
// Sessions end for reasons that have nothing to do with the policy -- a dropped
// socket, a world restart, a burst of packet errors -- and a fleet that quietly
// loses a character an hour still looks healthy on the stats line. So every
// character is supervised and re-logged in with backoff, and the report names
// anyone currently offline rather than averaging them away.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { startSession, type SessionEnd } from '../lite/session.js';
import { Agent } from './agent.js';
import { decide, rank } from './learn.js';
import { flush, load, meanXpPerWindow, peakWindow } from './memory.js';
import { thief } from './minds/thief.js';
import { applyPolicy, loadPolicy, savePolicy } from './policy.js';
import type { Mind } from './types.js';

/** How often the fleet re-ranks its own interchangeable rules. */
const LEARN_EVERY_MS = 120_000;

const RELOGIN_MS = 5_000;
const RELOGIN_MAX_MS = 60_000;

const args = process.argv.slice(2);
const names = args.filter(a => !a.startsWith('-'));
const minutes = Number(args.find(a => a.startsWith('--minutes='))?.split('=')[1] ?? 0);

if (!names.length) {
    console.error('usage: bun src/fleet/run.ts <bot> [<bot>...] [--minutes=N]');
    process.exit(1);
}

const ROOT = join(import.meta.dir, '../../../..');

function readEnv(name: string): Record<string, string> {
    const text = readFileSync(join(ROOT, 'bots', name, 'bot.env'), 'utf8');
    return Object.fromEntries(
        text
            .split('\n')
            .filter(l => l.includes('=') && !l.startsWith('#'))
            .map(l => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()])
    );
}

/**
 * Every character thieves; exactly one of them is the scorer.
 *
 * The scorer is simply the character the others hand their takings to. Under a
 * peak metric the fleet's score is whatever one character can convert in a
 * fifteen-second window, so the point of a fleet is to arrive at one moment
 * with everything concentrated in one pair of hands.
 */
const SCORER = names[0]!;

function mindFor(name: string): Mind {
    const role = name === SCORER ? 'scorer' : 'preparer';
    return applyPolicy(thief(name, role, SCORER), loadPolicy());
}

let shuttingDown = false;
const agents: Agent[] = [];

/**
 * The lite client speaks to the game server's own origin, which is not the
 * same address as the SDK gateway. `SERVER=localhost` in a bot.env means the
 * gateway on 7780; the engine serves the client on 8888, so a bare local host
 * needs the port spelled out or the connection is refused with no explanation.
 */
function gameHost(server: string | undefined): string {
    const host = server || 'localhost';
    if (host.includes(':')) return host;
    return host.startsWith('localhost') || host.startsWith('127.') ? `${host}:8888` : host;
}

async function login(agent: Agent): Promise<void> {
    const env = readEnv(agent.name);
    const session = await startSession({
        host: gameHost(env.SERVER),
        username: env.BOT_USERNAME!,
        password: env.PASSWORD!,
        quiet: true,
        onEnd: (end: SessionEnd) => onSessionEnd(agent, end)
    });
    agent.attach(session);
}

function onSessionEnd(agent: Agent, end: SessionEnd): void {
    if (shuttingDown || end.reason === 'stopped') return;
    console.warn(`[fleet] ${agent.name} lost its session (${end.reason}) - re-logging in`);
    void relogin(agent);
}

async function relogin(agent: Agent): Promise<void> {
    let delay = RELOGIN_MS;
    while (!shuttingDown) {
        await Bun.sleep(delay);
        if (shuttingDown) return;
        try {
            await login(agent);
            agent.relogins++;
            console.log(`[fleet] ${agent.name} back online`);
            return;
        } catch (e) {
            console.error(`[fleet] ${agent.name} re-login failed (${e}); retrying in ${Math.round(delay / 1000)}s`);
            delay = Math.min(delay * 2, RELOGIN_MAX_MS);
        }
    }
}

for (const name of names) {
    const agent = new Agent(mindFor(name));
    agents.push(agent);
    try {
        await login(agent);
        console.log(`[fleet] ${name} logged in`);
    } catch (e) {
        console.error(`[fleet] ${name} failed to log in: ${e}`);
        void relogin(agent);
    }
    await Bun.sleep(1500); // stagger; the login server refuses a stampede
}

if (!agents.some(a => a.online)) {
    console.error('[fleet] nothing logged in');
    process.exit(1);
}

const startedAt = Date.now();

/**
 * Re-rank and redeploy while the fleet runs.
 *
 * Learning on a schedule inside the run, rather than between runs, is what
 * lets exploration pay off: a shuffled order gets sampled, recorded and judged
 * within the same session, so a rule that only looks good on paper is demoted
 * while there is still time to benefit.
 */
const learner = setInterval(() => {
    flush();
    const rows = load();
    if (rows.length < 20) return;
    const arms = rank(rows, {
        explain: false,
        dryRun: false,
        coinWeight: 1,
        halfLife: 3600,
        epsilon: 0.2,
        minTrials: 5,
        lookahead: 0.3,
        gamma: 0.995,
        horizon: 15
    });
    const { policy, explored } = decide(arms, {
        explain: false,
        dryRun: false,
        coinWeight: 1,
        halfLife: 3600,
        epsilon: 0.2,
        minTrials: 5,
        lookahead: 0.3,
        gamma: 0.995,
        horizon: 15
    });
    savePolicy(policy);
    for (const agent of agents) agent.setMind(applyPolicy(mindFor(agent.name), policy));
    const best = arms[0];
    console.log(
        `[learn] re-ranked ${arms.length} arms` +
            (best ? `, best ${best.rule} ${best.value.toFixed(1)}/s over ${best.trials} trials` : '') +
            (explored.length ? ` | exploring: ${explored.join(', ')}` : '')
    );
}, LEARN_EVERY_MS);

const report = setInterval(() => {
    flush();
    const mins = (Date.now() - startedAt) / 60_000;
    const rows = load().filter(r => r.t >= startedAt);
    const peak = peakWindow(rows);
    const acts = agents.reduce((a, x) => a + x.outcomes, 0);
    const xp = agents.reduce((a, x) => a + x.xpGained, 0);
    const online = agents.filter(a => a.online).length;

    console.log(
        `\n[fleet] ${mins.toFixed(1)}m | ${online}/${agents.length} online | ${acts} actions ` +
            `(${(acts / Math.max(0.01, mins * 60)).toFixed(2)}/s) | ${xp} xp | ` +
            `peak ${peak.xp} xp/15s | mean ${meanXpPerWindow(rows).toFixed(0)} xp/15s`
    );
    for (const a of agents) {
        const b = a.latest;
        console.log(
            `  ${a.name.padEnd(9)} ${String(b?.hp ?? 0).padStart(2)}hp ` +
                `${String(b?.coins ?? 0).padStart(6)}gp | ${a.outcomes} acts ${a.xpGained} xp` +
                (a.lastFailure ? ` | last: ${a.lastFailure}` : '') +
                (a.online ? '' : '  <- OFFLINE')
        );
    }
}, 30_000);

function shutdown(): void {
    shuttingDown = true;
    clearInterval(report);
    clearInterval(learner);
    for (const a of agents) a.stop();
    flush();
    const rows = load().filter(r => r.t >= startedAt);
    const peak = peakWindow(rows);
    console.log(`\n[fleet] stopped. ${rows.length} actions recorded, peak ${peak.xp} xp in a 15s window.`);
    process.exit(0);
}

process.on('SIGINT', shutdown);
if (minutes > 0) setTimeout(shutdown, minutes * 60_000);
