#!/usr/bin/env python3
"""Write a short introduction for every zone, from its dossier (tools/dossier.py).

  python3 tools/intros.py [--only d3:haon_dor,...] [--force] [--jobs 4]

Three steps per zone, each a separate `claude -p` call with no tools:

  1. hints   reads ONLY the sealed half (quest guide section or DIL scripts) and turns
             each quest into one line of general language: no names, places, steps or
             rewards. Quests the guide marks DORMANT or BROKEN are dropped.
  2. write   reads ONLY the public half plus those hints and writes the introduction.
  3. check   reads the introduction, the public half and the sealed half, and fails it if
             it gives anything away or says something the public half doesn't support.
             A script check also fails any capitalised name that isn't in the public half.

A failed introduction is written again once with the problems; if it fails again it is
kept with status "failed" and never shown. Every introduction starts as "pending":
the map shows only those approved in the review (tools/review_sync.py).
Results go to tools/private/intros-work.json, keyed by zone, with the dossier's hash, so a
zone is only written again when its source changes (or with --force).
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSS = os.path.join(HERE, "tools/private/dossiers")
OUT = os.path.join(HERE, "tools/private/intros-work.json")  # hints and check notes quote spoilers: never committed
MODEL = "claude-opus-5-5"

HINTS = """You turn a game's quest notes into hints for a map that makes players curious. The notes are full
of spoilers; your hints must contain none of them.

Reply with JSON only: {"quests": [{"hint": "...", "status": "ok|dormant|broken|unknown", "for": "beginners|anyone|veterans|unknown"}]}

For each quest in the notes, one hint of at most 10 words, in general language:
- say only the KIND of task, from: an errand, a favour, a hunt, a search for something lost, a riddle,
  a trial, a rescue, a long journey; and, if you like, the generic KIND of reward, from: a weapon,
  armour, a trinket, a blessing, gold, a reward
- never WHAT is sought, made, said or done (not "writings", "a pledge", "an offering", "stew
  ingredients"): only "something lost", "something precious", "a task"
- never a name of a person, creature, god, place, item or group; never a step, command, number,
  location, other zone, or what the reward is or does; never who gives the quest
- good: "an errand for beginners, rewarded with a trinket", "a quest for a powerful weapon",
  "a trial that only the brave complete", "a search for something precious"
- bad: "help Mary make stew" (a name and the task), "find the six pieces of Ariakas' sword" (names and
  structure), "a solemn pledge that earns protection" (what is done and what the reward does)
status: use the notes' own OK / DORMANT / BROKEN when given; otherwise "unknown" unless the scripts
plainly cannot run. If the notes or scripts hold no quest a player can take on, reply {"quests": []}.
Scripts that only make monsters move, talk, fight or guard are not quests."""

WRITE = """You write the short introduction to one area of Valhalla, a fantasy text adventure game (a MUD), for
its world map. The goal: a player reads it and wants to go there. Tantalise; never explain.

Reply with JSON only: {"intro": "...", "teaser": "...", "sources": ["phrase from intro -> dossier field it comes from", ...]}

intro: 45 to 75 words. Voice: a well-travelled storyteller in a Midgaard tavern, speaking to the reader
("you"). Evocative and concrete, not purple; no clichés like "brave adventurer" or "await".
Pick the two or three most intriguing details and leave the rest unsaid: never a list of rooms.
teaser: one sentence of at most 16 words, the hook, for a tooltip.
Rules:
- Use ONLY what the dossier says. Every concrete detail (a creature, a place, a sight) must be in it;
  list each in "sources". Invent nothing: no history, names or dangers it doesn't give.
- Proper names only if they appear in the dossier's public fields.
- Say how dangerous it is in words that fit the levels (1-10 novices, 10-25 those with some
  experience, 25-40 seasoned, 40+ only the mightiest), never as numbers.
- Quests: only through the hints given, in their general language, as rumour ("they say ...").
  Add no detail to a hint. No hints: don't mention quests.
- Keep secrets: no hidden exits, puzzles, passwords, solutions, item powers or where treasure lies.
- Never mention game mechanics, numbers, levels, zones, builders, code, DikuMUD or the map itself."""

CHECK = """You check one introduction for a game's world map. You see the introduction, the public facts it may
use, and the SECRET notes (quest solutions and scripts) it must not reveal.

Reply with JSON only: {"verdict": "pass" | "fail", "problems": ["...", ...]}

You also see the APPROVED quest hints: general lines already cleared as spoiler-free. The introduction
may pass these on as rumour in its own words (that is not a leak or an invention); anything about a
quest beyond what a hint says is.

Fail it if it does ANY of these:
- reveals anything from the secret notes beyond the general kind of quest: a quest giver, an item,
  a step, a command, a location, a reward's name or power, a password, a hidden exit, a puzzle's answer
- names any person, creature, place or item that appears only in the secret notes
- states something the public facts don't support (an invented creature, place, event or danger)
- describes the danger in a way that contradicts the public levels
- mentions game mechanics, numbers, levels, builders, code or the map
Be strict about secrets and invention; don't fail it for style."""


def claude(system, prompt):
    r = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--no-session-persistence",
                        "--disable-slash-commands", "--output-format", "json", "--system-prompt", system],
                       input=prompt, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(f"claude -p exit {r.returncode}: {(r.stderr or r.stdout)[-500:]}")
    text = json.loads(r.stdout)["result"]
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("no JSON in reply: " + text[:300])
    return json.loads(m.group(0))


def names_not_public(intro, public):
    """Capitalised words that aren't the start of a sentence and aren't in the public half."""
    pub = json.dumps(public, ensure_ascii=False).lower()
    out = []
    for m in re.finditer(r"(?<![.!?\"“]\s)(?<!^)\b([A-Z][a-z'’-]+)", intro):
        w = m.group(1).rstrip("'’s")
        if w.lower() not in pub and w not in ("Midgaard", "Valhalla", "You", "They", "I"):
            out.append(w)
    return sorted(set(out))


def one(key, d):
    sealed = d["sealed"]
    if sealed["quest_guide"] or sealed["has_dil_quest"]:
        src = sealed["quest_guide"] or sealed["dil"]
        hints = claude(HINTS, "Quest notes:\n\n" + src[:60000])["quests"]
    else:
        hints = []
    usable = [h for h in hints if h.get("status") in ("ok", "unknown")]
    pub = json.dumps(d["public"], ensure_ascii=False, indent=1)
    feedback, result = "", None
    for attempt in (1, 2):
        w = claude(WRITE, f"Dossier (public):\n{pub}\n\nQuest hints:\n{json.dumps([h['hint'] for h in usable])}"
                   + (f"\n\nAn earlier draft was rejected for: {feedback}\nWrite a new one." if feedback else ""))
        intro, teaser = w["intro"].strip(), w["teaser"].strip()
        bad_names = names_not_public(intro + " " + teaser, d["public"])
        c = claude(CHECK, f"Introduction:\n{intro}\n\nTooltip:\n{teaser}\n\nPublic facts:\n{pub}\n\n"
                          f"APPROVED quest hints:\n{json.dumps([h['hint'] for h in usable])}\n\n"
                          f"SECRET notes:\n{(sealed['quest_guide'] or sealed['dil'])[:60000]}")
        problems = c.get("problems", []) if c.get("verdict") != "pass" else []
        if bad_names:
            problems.append("names not in the public facts: " + ", ".join(bad_names))
        words = len(intro.split())
        if not 35 <= words <= 90:
            problems.append(f"{words} words")
        result = dict(intro=intro, teaser=teaser, sources=w.get("sources", []), hints=hints,
                      check=problems, attempts=attempt, hash=d["source_hash"],
                      status="pending" if not problems else "failed")
        if not problems:
            break
        feedback = "; ".join(problems)
    return key, result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    index = json.load(open(os.path.join(DOSS, "index.json")))
    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = []
    for key, v in sorted(index.items()):
        if "file" not in v or (a.only and key not in a.only.split(",")):
            continue
        prev = done.get(key)
        if prev and prev["hash"] == v["hash"] and not a.force:
            continue
        todo.append((key, json.load(open(os.path.join(DOSS, v["file"])))))
    print(f"{len(todo)} to write", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(one, k, d): k for k, d in todo}
        for f in concurrent.futures.as_completed(futs):
            k = futs[f]
            try:
                _, r = f.result()
            except Exception as e:  # keep going; the zone is tried again next run
                print(f"{k}: ERROR {e}", file=sys.stderr)
                continue
            prev = done.get(k)
            if prev and prev.get("status") == "approved" and prev.get("intro") == r["intro"]:
                r["status"] = "approved"
            done[k] = r
            print(f"{k}: {r['status']} ({r['attempts']} tries) {'; '.join(r['check'])}", file=sys.stderr)
            json.dump(done, open(OUT, "w"), indent=1, ensure_ascii=False, sort_keys=True)
    # twins and skipped zones are listed so the map knows where an introduction comes from
    s = [v["status"] for v in done.values()]
    print(f"intros.json: {len(done)} zones, " + ", ".join(f"{x} {s.count(x)}" for x in sorted(set(s))), file=sys.stderr)


if __name__ == "__main__":
    main()
