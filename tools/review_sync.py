#!/usr/bin/env python3
"""Carry the zone introductions to the review page and the decisions back.

  python3 tools/review_sync.py export            > tools/private/review-rows.json
  python3 tools/review_sync.py apply ROWS.json   (the review page's rows, read back)

export  one row per introduction in tools/private/intros-work.json, for the review page's
        "intros" collection (doc id = zone key with ':' as '_').
apply   writes intros.json: the approved introductions only (an edited text replaces the
        written one), with no hints or check notes, since this file is published.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(HERE, "tools/private/intros-work.json")
DOSS = os.path.join(HERE, "tools/private/dossiers")
OUT = os.path.join(HERE, "intros.json")


def export():
    work = json.load(open(WORK))
    index = json.load(open(os.path.join(DOSS, "index.json")))
    rows = []
    for key, i in sorted(work.items()):
        pub = json.load(open(os.path.join(DOSS, index[key]["file"])))["public"]
        rows.append(dict(id=key.replace(":", "_"), data=dict(
            key=key, title=pub["title"], game=pub["game"], levels=pub["levels"], intro=i["intro"], teaser=i["teaser"],
            hints=[dict(hint=h["hint"], status=h["status"]) for h in i["hints"]], check=i["check"],
            status=i["status"], edited="", editedTeaser="", hash=i["hash"])))
    json.dump(rows, sys.stdout, indent=1, ensure_ascii=False)


def apply(path):
    rows = json.load(open(path))
    rows = rows.get("documents", rows) if isinstance(rows, dict) else rows
    out, counts = {}, {}
    for r in rows:
        d = r.get("data", r)
        counts[d["status"]] = counts.get(d["status"], 0) + 1
        if d["status"] == "approved":
            out[d["key"]] = dict(intro=d.get("edited") or d["intro"], teaser=d.get("editedTeaser") or d["teaser"],
                                 edited=bool(d.get("edited") or d.get("editedTeaser")), hash=d["hash"])
    json.dump(out, open(OUT, "w"), indent=1, ensure_ascii=False, sort_keys=True)
    print(f"intros.json: {len(out)} approved; " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:2] == ["export"]:
        export()
    elif sys.argv[1:2] == ["apply"] and len(sys.argv) == 3:
        apply(sys.argv[2])
    else:
        sys.exit(__doc__)
