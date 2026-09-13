#!/usr/bin/env python3
"""Keep characters connected, and keep their combat style off Defence.

Two failures this guards against, both of which have actually happened here.

**Sessions drop, and nothing notices.** A dropped session is indistinguishable
from a terrain wall: every action is accepted, nothing moves, and a scripted
expedition can run its whole length against a dead connection. Worse, when
nobody is playing there is no walker to notice -- characters sat offline for
hours with every recipe idle and no error anywhere, because the error only
appears when something asks.

**Combat style silently reverts on reconnect.** It goes back to index 0, and on
a scimitar index 0 is Chop/Accurate, which trains Attack. Auto-retaliate is on
by default, so a character that gets attacked while nobody is looking trains a
skill it was never meant to have. That is how Arete's Attack went 43 to 57 and
her combat level 75 to 80, permanently, on a build that wanted neither.

**Style is chosen by reading, never by index.** This is the part worth copying
elsewhere: style indices are per-weapon. `--style 1` is Slash/Aggressive on a
scimitar and something else on a different weapon, so hardcoding an index can
put a character on Lunge (Attack, Strength AND Defence) or Block (Defence) the
moment its weapon changes. This reads `trainsSkills` from the live state and
picks a style that trains what was asked for and **never** trains a forbidden
skill. If no style qualifies, it changes nothing and says so, because leaving
the style alone is always safer than guessing.

    python3 recipes/keepalive.py --characters arete scout1 scout2
    python3 recipes/keepalive.py --characters arete --forbid Defence Magic

Run it in the background for the whole session. It is cheap: one state read per
character per interval, and it acts only when something is wrong.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)

# Arete is a pure build: training Defence cannot be undone and ends the
# character's purpose. Any character may add to this with --forbid.
DEFAULT_FORBID = ("Defence",)


def cli(character, *args):
    r = subprocess.run(
        ["python3", "clawscape.py", "--character", character] + list(args),
        capture_output=True,
        text=True,
        cwd=CLI_DIR,
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def emit(**kw):
    kw["t"] = time.strftime("%H:%M:%S")
    print(json.dumps(kw, separators=(",", ":")), flush=True)


def state(character):
    return cli(character, "state", "--full").get("state")


def connect(character):
    return cli(character, "connect", "--character", character).get("connected")


def choose_style(combat_style, want, forbid):
    """Index of a style that trains `want` and none of `forbid`.

    Returns None when nothing qualifies, which must be treated as "leave it
    alone" -- a wrong style is worse than an unchanged one.
    """
    styles = (combat_style or {}).get("styles") or []
    safe = [
        s
        for s in styles
        if not (set(s.get("trainsSkills") or []) & set(forbid))
        and s.get("trainsSkills")
    ]
    for s in safe:
        if want in (s.get("trainsSkills") or []):
            return s.get("index")
    return safe[0].get("index") if safe else None


def check(character, want, forbid):
    """One pass over one character. Returns a dict describing what it did."""
    d = state(character)
    if not d:
        if not connect(character):
            return {"character": character, "offline": True, "reconnect": "failed"}
        d = state(character)
        if not d:
            return {"character": character, "offline": True, "reconnect": "no_state"}
        out = {"character": character, "reconnected": True}
    else:
        out = {"character": character}

    cs = d.get("combatStyle") or {}
    cur = cs.get("currentStyle")
    styles = cs.get("styles") or []
    trains = set()
    if cur is not None and 0 <= cur < len(styles):
        trains = set(styles[cur].get("trainsSkills") or [])

    bad = trains & set(forbid)
    want_idx = choose_style(cs, want, forbid)
    if bad or (want not in trains and want_idx is not None and want_idx != cur):
        if want_idx is None:
            out["style"] = "no_safe_style_left_alone"
        else:
            cli(
                character,
                "act",
                "setCombatStyle",
                "--json",
                json.dumps({"style": want_idx}),
            )
            out["style_set"] = want_idx
            out["was_training"] = sorted(trains)
            if bad:
                out["FORBIDDEN"] = sorted(bad)

    p = d.get("player") or {}
    out["at"] = [p.get("worldX"), p.get("worldZ")]
    out["hp"] = p.get("hp")
    for s in d.get("skills") or []:
        if s.get("name") in forbid:
            out[s["name"]] = s.get("baseLevel")
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--characters", nargs="+", required=True)
    ap.add_argument("--interval", type=int, default=90, help="seconds between passes")
    ap.add_argument("--want", default="Strength", help="skill the style should train")
    ap.add_argument("--forbid", nargs="*", default=list(DEFAULT_FORBID))
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)

    emit(keepalive="start", characters=a.characters, want=a.want, forbid=a.forbid)
    while True:
        for c in a.characters:
            try:
                r = check(c, a.want, a.forbid)
            except Exception as e:  # never let one character stop the watch
                r = {"character": c, "error": str(e)[:120]}
            # Quiet unless something happened: a heartbeat every 90s for three
            # characters is noise that hides the one line that matters.
            if len(r) > 4 or "error" in r or "offline" in r:
                emit(**r)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
