# Setup and recovery

Commands below use `python3 clawscape.py` from the skill directory. Pass
`--character NAME` on character commands; shared login/default settings affect
other agents on the same machine.

## Login or new character

Use the existing login when available. Otherwise obtain the owner's username
and password. Run `auth login USER --password-stdin`, or `auth register USER
--password-stdin` for a new account, supplying the password on stdin. Success
has `authenticated: true`. There is no self-service password recovery; tell the
owner to keep the password safe. Login is stored in `~/.clawscape`.

Create a character only when requested with `characters create NAME`: 1–12
lowercase letters/digits starting with a letter. Run `connect` then `state`.
Use `--server URL` for another world; it is remembered after login.

## Tutorial

A new character may first need `act acceptCharacterDesign`, then `wait 2`.
Find `RuneScape Guide` with `state npcs --name guide` and send `act talkToNpc`
with its `npcIndex`. Inspect `state dialog` after waiting.

When `dialog.isOpen` and not `dialog.isWaiting`, select the Yes option using
`act clickDialogOption --json '{"optionIndex":N}'`. N is the option's `index`
in the current dialog, counting from 1. **0 means continue only on a page
without choices.** Sending 0 against Yes/No causes `client_rejected`; repeating
it cannot advance the tutorial. Continue through non-choice pages as needed.
Verify Lumbridge world position and the starter kit in inventory before training.

## Session recovery

The world retains a session between commands. Thirty minutes without calls logs
it out. Selecting another character does not disconnect the first. If disconnected,
run `connect` and inspect fresh state. If authentication fails, log in again.

`disconnect` requests logout and saving; normal logout rules still apply.
Unattended characters can be attacked or die. Disconnect when the owner wants
it offline or the assigned task calls for logout. A connection-cap error may
require another character to disconnect; coordinate with its acting agent.
`auth logout` revokes the shared login; disconnect live characters first.

If neither runtime is available, use the packaged `openapi.json` to make HTTP
requests directly. No local game server is needed.
