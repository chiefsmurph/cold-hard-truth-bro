#!/opt/homebrew/bin/python3
import json, re, sys
from cht_common import creators, DATA
from pathlib import Path
SLUG = sys.argv[1] if len(sys.argv) > 1 else "example-creator"
ROOT = DATA
docs = [json.loads(p.read_text()) for p in (ROOT / "transcripts" / SLUG).glob("*.json")]
fp = ROOT / "failures.json"
fails = json.loads(fp.read_text()) if fp.exists() else {}
vids = [d for d in docs if d.get("kind") != "stream"]
streams = [d for d in docs if d.get("kind") == "stream"]
hours = sum(d.get("duration_s") or 0 for d in docs) / 3600
words = sum(d["word_count"] for d in docs)
TOPICS = [("texting", r"text|dm|message"), ("pulling away", r"pull(ing|ed)? away|ghost|distan|ignor"),
          ("dates", r"date|dating|approach|pick.?up|meet"), ("tests", r"\btests?\b|shit.?test"),
          ("relationships", r"relationship|girlfriend|boyfriend|wife|marriage|ex\b|breakup|cheat"),
          ("confidence", r"confiden|self.?esteem|frame|alpha|attract")]
tally = {t: 0 for t, _ in TOPICS}; tally["other"] = 0
for d in docs:
    hit = [t for t, p in TOPICS if re.search(p, d["title"], re.I)]
    for t in hit: tally[t] += 1
    if not hit: tally["other"] += 1
L = [f"# Coverage: {creators()[SLUG]['channel']}", "",
     f"- Videos collected: {len(vids)}", f"- Livestreams collected: {len(streams)}",
     f"- Total hours: {hours:.1f}", f"- Total words: {words:,}",
     f"- Average words per video: {words // max(len(docs), 1):,}", "", "## Top 15 by views"]
for d in sorted(docs, key=lambda d: d.get("view_count") or 0, reverse=True)[:15]:
    L.append(f"- {d.get('view_count') or 0:,}: {d['title']} ({d['video_id']})")
L += ["", f"## Failures ({len(fails)})"] + [f"- {k}: {v['title']} - {v['reason']}" for k, v in fails.items()]
L += ["", "## Title topic tally (a title can count in several)"] + [f"- {t}: {n}" for t, n in tally.items()]
out = ROOT / "reports" / f"coverage-{SLUG}.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(L) + "\n")
print(out)
