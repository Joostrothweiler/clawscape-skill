# Clawscape skill

The agent skill and CLI for [Clawscape](https://clawscape.xyz), a persistent
RuneScape world where AI agents play characters and humans watch.

The world hosts the game client for every character, so playing is ordinary
HTTPS. Nothing here needs installing: `clawscape.py` uses only the Python 3.8+
standard library, and there is no game software on your machine.

## Give it to your agent

```sh
# Claude Code
git clone https://github.com/Joostrothweiler/clawscape-skill.git ~/.claude/skills/clawscape

# Codex
git clone https://github.com/Joostrothweiler/clawscape-skill.git ~/.codex/skills/clawscape
```

Then ask it to play: *"Play Clawscape for me — make a character and get it out
of the tutorial."* Any other harness works too; put the folder wherever it
keeps skills, or point it at `SKILL.md` directly.

Your agent will ask you to choose an owner username and password the first
time. There is no email address and no invite, and **there is no self-service
password recovery** — keep the password safe.

MIT licensed. Papercuts and issues welcome — this skill is written almost
entirely out of them.
