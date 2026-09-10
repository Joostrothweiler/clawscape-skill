// The rungs every character needs before any of them can do its job.
//
// These sit above every ladder. Two of them unblock the server (a dialog or a
// modal makes the engine accept ops and never run them, with no message), and
// the rest walk a brand-new account off Tutorial Island.
//
// Escaping the tutorial belongs in the ladder rather than in a setup script.
// A script has to be run, remembered, and re-run whenever an account is
// replaced; a rule notices the island and leaves, so pointing the fleet at
// five fresh names on any server is the whole of the setup. It is also
// self-healing: a character that somehow ends up back in a dialog gets out on
// its own instead of spending the run dispatching walk commands the server
// discards -- which is exactly how one of ours burned 300 actions for 0 xp.

import type { Rule } from '../types.js';

/** The character design modal. Blocks everything until it is answered. */
const DESIGN_MODAL = 3559;

export const prelude: Rule[] = [
    {
        name: 'accept_character_design',
        when: b => b.modalOpen && b.modalInterface === DESIGN_MODAL,
        then: () => ({
            action: { type: 'acceptCharacterDesign', reason: 'leave the design screen' },
            done: b => !b.modalOpen || b.modalInterface !== DESIGN_MODAL,
            ticks: 4
        })
    },
    {
        // A dialog mid-animation will not take a click. Sending one anyway is
        // the refusal that shows up as `rejected` and teaches a learner that
        // whichever rule fired is worthless.
        name: 'let_dialog_settle',
        when: b => b.dialogOpen && b.dialogWaiting,
        then: () => ({ action: { type: 'wait', ticks: 1, reason: 'dialog animating' }, ticks: 2 })
    },
    {
        // Prefer the option that ends the conversation fastest. Ordering is
        // never assumed -- options are matched by their own text, because the
        // same dialog publishes its buttons in different orders in different
        // places.
        name: 'answer_dialog',
        when: b => b.dialogOpen,
        then: b => {
            const options = b.dialogOptions;
            const pick =
                options.find(o => /skip|complete|finish/i.test(o.text)) ??
                options.find(o => /yes|continue|proceed/i.test(o.text)) ??
                options.find(o => /confirm|accept|agree|ok/i.test(o.text)) ??
                options[0];
            return {
                action: { type: 'clickDialogOption', optionIndex: pick?.index ?? 0, reason: 'advance dialog' },
                done: after => !after.dialogOpen || after.dialogOptions !== options,
                ticks: 4
            };
        }
    },
    {
        // Any other modal -- a level-up, a shop left open -- replaces the
        // inventory tab, so inventory packets sent underneath it are rejected
        // as "component not visible", silently.
        name: 'close_modal',
        when: b => b.modalOpen,
        then: () => ({
            action: { type: 'closeModal', reason: 'unblock inventory' },
            done: b => !b.modalOpen,
            ticks: 3
        })
    },
    {
        // Still on the island with nothing open: talk to whoever is nearest.
        // The tutorial advances by conversation, and `answer_dialog` above
        // handles whatever the conversation turns into.
        name: 'leave_tutorial_island',
        when: b => onTutorialIsland(b.state.player?.worldX ?? 0, b.state.player?.worldZ ?? 0),
        then: b => {
            const guide = b.npc(/guide|instructor|expert|advisor|master/i, /talk-to/i);
            if (!guide) return null;
            return {
                action: { type: 'talkToNpc', npcIndex: guide.index, reason: 'advance the tutorial' },
                done: after => after.dialogOpen,
                ticks: 8
            };
        }
    },
    {
        // On the island with nobody to talk to. Every rule below this one aims
        // at a destination that is not routable from here, so letting them try
        // costs an action per tick and earns nothing -- which is precisely how
        // a character logged 300 actions and 0 xp while looking busy. Idling
        // is honest, and the report shows it as idling.
        name: 'stranded_on_the_island',
        when: b => onTutorialIsland(b.state.player?.worldX ?? 0, b.state.player?.worldZ ?? 0),
        then: () => ({ action: { type: 'wait', ticks: 2, reason: 'no guide in view' }, ticks: 3 })
    }
];

/** Tutorial Island's own corner of the map, well away from anywhere useful. */
export function onTutorialIsland(x: number, z: number): boolean {
    return x >= 3050 && x <= 3140 && z >= 3050 && z <= 3140;
}
