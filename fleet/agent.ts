// One character: a lite client, a ladder, and a loop.
//
// The loop runs on the engine's own tick callback rather than a timer, so an
// action costs the ticks the engine actually needs and not a round trip we
// invented. That is the entire performance argument for this layer: the same
// work driven through the SDK gateway costs a WebSocket RTT plus a full state
// broadcast before the next action can even be aimed.
//
// The kernel holds exactly one Intent at a time and will not consider another
// rule until that Intent resolves. A dispatched op is not an accepted op --
// the engine refuses ops it will not run (mid-action, stunned, target gone,
// modal open) by answering UNSET_MAP_FLAG and nothing else -- so resolution is
// decided by observed evidence, by an explicit rejection count, or by a
// deadline, and never by the fact that we sent something.

import { BotStateCollector } from '#/bot/StateCollector.js';
import { ActionExecutor } from '#/bot/ActionExecutor.js';
import type { BotAction, BotWorldState } from '#/bot/types.js';
import type { Client } from '#/client/Client.js';
import type { LiteSession } from '../lite/session.js';
import type { LiteClient } from '../lite/LiteClient.js';

import { beliefs, totalXp, xpBySkill } from './beliefs.js';
import { remember } from './memory.js';
import type { Beliefs, Intent, Mind, Outcome, Resolution, Rule } from './types.js';

/** Fallback deadline for an Intent that did not name one. */
const DEFAULT_TICKS = 8;

interface InFlight {
    rule: Rule;
    intent: Intent;
    sentTick: number;
    sentAt: number;
    rejectCursor: number;
    xpBefore: number;
    xpBySkillBefore: Record<string, number>;
    coinsBefore: number;
}

export class Agent {
    private session: LiteSession | null = null;
    private client: LiteClient | null = null;
    private collector: BotStateCollector | null = null;
    private executor: ActionExecutor | null = null;

    private tick = 0;
    private cooldown = 0;
    private routing = false;
    private flight: InFlight | null = null;
    /** Last total XP seen, and how many ticks it has held steady. */
    private baseline = -1;
    private settled = 0;

    /** Latest beliefs, for the reporter and for cross-agent coordination. */
    latest: Beliefs | null = null;
    outcomes = 0;
    xpGained = 0;
    relogins = 0;
    lastFailure = '';

    constructor(private mind: Mind) {}

    get name(): string {
        return this.mind.name;
    }

    get rules(): Rule[] {
        return this.mind.rules;
    }

    /**
     * Swap in a re-ranked ladder mid-run.
     *
     * Safe at any moment because rules hold no state: an Intent already in
     * flight is judged by the closure that created it, and the next choice
     * simply reads the new order. This is what makes learning continuous
     * rather than something that only takes effect on restart.
     */
    setMind(mind: Mind): void {
        this.mind = mind;
    }

    get online(): boolean {
        return this.client !== null && this.client.isInGame();
    }

    /**
     * Take ownership of a freshly logged-in session.
     *
     * Everything keyed to the old session is reset: npc indices are per-session
     * and the tick counter restarts at zero, so a deadline carried across a
     * re-login reads as far-future and would never expire.
     */
    attach(session: LiteSession): void {
        this.session = session;
        this.client = session.client;
        const asClient = this.client as unknown as Client;
        this.collector = new BotStateCollector(asClient);
        this.executor = new ActionExecutor(asClient);
        this.executor.setScanProvider(this.collector);

        this.tick = 0;
        this.cooldown = 0;
        this.routing = false;
        this.flight = null;
        this.baseline = -1;
        this.settled = 0;

        this.client.setOnGameTickCallback(() => {
            this.tick++;
            try {
                this.onTick();
            } catch (e) {
                console.error(`[${this.name}] tick error:`, e);
            }
        });
    }

    stop(): void {
        this.client?.setOnGameTickCallback(null);
        this.session?.stop();
        this.session = null;
        this.client = null;
    }

    private onTick(): void {
        if (!this.collector) return;
        // A long walk resolves off-tick; let it finish before aiming anything.
        if (this.routing) return;

        const state = this.collector.collectState(this.tick, true) as BotWorldState | null;
        if (!state?.player) return;
        // Wait for the XP baseline to stop moving before acting.
        //
        // Skills arrive after the player does, and they arrive zeroed before
        // they arrive correct. Either way the first action to resolve is
        // credited with the whole difference -- observed as "6305 xp in 11
        // pickpockets", which is also enough to set a fake peak window and
        // teach the learner to repeat whatever happened to fire at login.
        // Requiring two consecutive ticks to agree costs one tick per session
        // and removes the entire class of error.
        const total = totalXp(state);
        if (this.baseline !== total) {
            this.baseline = total;
            this.settled = 0;
            return;
        }
        if (this.settled < 1) {
            this.settled++;
            return;
        }

        const b = beliefs(this.name, this.mind.role, this.tick, state);
        this.latest = b;

        if (this.flight) {
            const res = this.judge(b);
            if (!res) return; // still in flight
            this.settle(b, res);
            if (this.cooldown > 0) return;
        }
        if (this.cooldown > 0) {
            this.cooldown--;
            return;
        }
        this.choose(b);
    }

    /** Has the in-flight Intent resolved, and how? */
    private judge(b: Beliefs): Resolution | null {
        const f = this.flight!;
        // An explicit refusal. The closest thing to a negative ack that exists,
        // and far better than waiting out the whole deadline for a resolution
        // that was never coming.
        if (b.state.opFeedback.opRejectedCount > f.rejectCursor) return 'rejected';
        if (f.intent.done?.(b)) return 'done';
        const deadline = f.intent.ticks ?? DEFAULT_TICKS;
        if (this.tick - f.sentTick >= deadline) return 'timeout';
        // An Intent with no evidence to wait for is complete on dispatch. Rules
        // should avoid this: it is exactly the "dispatch == effect" conflation
        // that makes a reward signal meaningless.
        if (!f.intent.done) return 'done';
        return null;
    }

    private settle(b: Beliefs, resolution: Resolution): void {
        const f = this.flight!;
        this.flight = null;

        const xpNow = totalXp(b.state);
        const bySkillNow = xpBySkill(b.state);
        const delta: Record<string, number> = {};
        for (const [skill, value] of Object.entries(bySkillNow)) {
            const gained = value - (f.xpBySkillBefore[skill] ?? value);
            if (gained > 0) delta[skill] = gained;
        }
        const xp = Math.max(0, xpNow - f.xpBefore);

        const row: Outcome = {
            t: Date.now(),
            character: this.name,
            role: this.mind.role,
            rule: f.rule.name,
            group: f.rule.group,
            resolution,
            ticks: this.tick - f.sentTick,
            ms: Date.now() - f.sentAt,
            xp,
            coins: Math.max(0, b.coins - f.coinsBefore)
        };
        if (Object.keys(delta).length) row.xpBySkill = delta;
        remember(row);

        try {
            f.intent.onResolve?.(resolution, b);
        } catch (e) {
            console.error(`[${this.name}] onResolve for ${f.rule.name} threw:`, e);
        }

        this.outcomes++;
        this.xpGained += xp;
        if (resolution !== 'done') this.lastFailure = `${f.rule.name}:${resolution}`;
        if (f.intent.cooldown) this.cooldown = f.intent.cooldown;
    }

    /** First rule whose `when` holds and whose `then` yields a runnable Intent. */
    private choose(b: Beliefs): void {
        for (const rule of this.mind.rules) {
            let intent: Intent | null = null;
            try {
                if (!rule.when(b)) continue;
                intent = rule.then(b);
            } catch (e) {
                console.error(`[${this.name}] rule ${rule.name} threw:`, e);
                continue;
            }
            if (!intent) continue;
            this.dispatch(b, rule, intent);
            return;
        }
        this.lastFailure = 'no_rule_matched';
    }

    private dispatch(b: Beliefs, rule: Rule, intent: Intent): void {
        if (!this.executor) return;
        const f: InFlight = {
            rule,
            intent,
            sentTick: this.tick,
            sentAt: Date.now(),
            rejectCursor: b.state.opFeedback.opRejectedCount,
            xpBefore: totalXp(b.state),
            xpBySkillBefore: xpBySkill(b.state),
            coinsBefore: b.coins
        };
        this.flight = f;

        const result = this.executor.execute(intent.action as BotAction);
        if (result instanceof Promise) {
            // Only long-distance routing goes async.
            this.routing = true;
            result
                .catch(() => undefined)
                .finally(() => {
                    this.routing = false;
                });
            return;
        }
        if (!result.success) {
            // The client never wrote a packet -- usually it could not route.
            // Settle immediately rather than burning the deadline waiting for
            // evidence of something that was never sent.
            this.lastFailure = `${rule.name}:${result.reason ?? result.message}`;
            this.settle(b, 'blocked');
        }
    }
}
