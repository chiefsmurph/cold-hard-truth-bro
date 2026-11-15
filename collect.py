#!/opt/homebrew/bin/python3
"""Stage 1: collect English subtitles for one creator and clean to JSON."""
import json, re, subprocess, sys, time, random, shutil, tempfile
from pathlib import Path

import os
from cht_common import creators, DATA
YTDLP = os.environ.get("YTDLP") or shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
CREATOR = sys.argv[1] if len(sys.argv) > 1 else "example-creator"  # slug, defined in creators.json
_c = creators()[CREATOR]
CHANNEL, HANDLE = _c["channel"], _c["handle"]
ROOT = DATA
OUT = ROOT / "transcripts" / CREATOR
KEYWORDS = ["text", "texting", "pulling away", "first date", "test", "ghost", "cheat",
            "girlfriend", "relationship", "confidence", "approach"]
N_TOP, N_KW, N_STREAMS, MIN_DUR = 50, 30, 10, 120


def flat(tab):
    r = subprocess.run([YTDLP, "--flat-playlist", "-J", f"https://www.youtube.com/{HANDLE}/{tab}"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return [e for e in json.loads(r.stdout).get("entries", []) if e and e.get("id")]


def select():
    cache = ROOT / "selection.json"
    if cache.exists():
        return json.loads(cache.read_text())
    vids = [v for v in flat("videos") if (v.get("duration") or 0) >= MIN_DUR]
    vids.sort(key=lambda v: v.get("view_count") or 0, reverse=True)
    top = vids[:N_TOP]
    seen = {v["id"] for v in top}
    pat = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.I)
    kw = [v for v in vids[N_TOP:] if pat.search(v.get("title", ""))][:N_KW]
    seen |= {v["id"] for v in kw}
    streams = [s for s in flat("streams") if (s.get("duration") or 0) >= 1200 and s["id"] not in seen]
    # stream view counts mostly missing: take the most viewed known, else most recent (list order)
    streams.sort(key=lambda s: -(s.get("view_count") or 0))  # stable: keeps recency among ties
    streams = streams[:N_STREAMS]
    sel = [dict(v, kind="video") for v in top + kw] + [dict(s, kind="stream") for s in streams]
    ROOT.mkdir(exist_ok=True)
    cache.write_text(json.dumps(sel, indent=1))
    return sel


TS = re.compile(r"(\d+):(\d+):(\d+)[.,](\d+) --> ")


def clean_vtt(text):
    segs, last_line, next_t = [], "", -1
    cur_t, cur = 0, []
    for block in re.split(r"\n\s*\n", text):
        lines = block.strip().splitlines()
        m = None
        for i, l in enumerate(lines):
            m = TS.match(l)
            if m:
                body = lines[i + 1:]
                break
        if not m:
            continue
        t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        for l in body:
            l = re.sub(r"<[^>]+>", "", l).replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
            l = re.sub(r"\[[^\]]*\]", "", l).strip()  # [Music] etc.
            if not l or l == last_line:
                continue
            last_line = l
            if t >= next_t:
                if cur:
                    segs.append({"t": cur_t, "text": " ".join(cur)})
                cur, cur_t, next_t = [], t, t + 30
            cur.append(l)
    if cur:
        segs.append({"t": cur_t, "text": " ".join(cur)})
    return segs


def fetch(v, tmp):
    cmd = [YTDLP, "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", "en",
           "--sub-format", "vtt", "--write-info-json", "--sleep-requests", "1",
           "--sleep-interval", "2", "--max-sleep-interval", "4",
           "-o", str(tmp / "%(id)s"), f"https://www.youtube.com/watch?v={v['id']}"]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    sel = select()
    OUT.mkdir(parents=True, exist_ok=True)
    fails = ROOT / "failures.json"
    failures = json.loads(fails.read_text()) if fails.exists() else {}
    blocked = 0
    for i, v in enumerate(sel, 1):
        vid = v["id"]
        if (OUT / f"{vid}.json").exists():
            continue
        tmp = Path(tempfile.mkdtemp(prefix="cht-"))
        try:
            r = fetch(v, tmp)
            err = (r.stderr or "")[-300:].replace("\n", " ")
            vtts = list(tmp.glob(f"{vid}*.vtt"))
            info_f = tmp / f"{vid}.info.json"
            if not vtts:
                reason = "429/bot-check" if ("429" in err or "confirm you" in err or "Sign in" in err) \
                    else ("no english subtitles" if r.returncode == 0 else f"error: {err}")
                failures[vid] = {"title": v.get("title"), "reason": reason}
                blocked = blocked + 1 if reason == "429/bot-check" else 0
                print(f"[{i}/{len(sel)}] FAIL {vid} {reason}", flush=True)
                fails.write_text(json.dumps(failures, indent=1))
                if blocked >= 3:
                    print("Repeated 429/bot checks: stopping.", flush=True)
                    sys.exit(2)
                time.sleep(random.uniform(2, 4))
                continue
            blocked = 0
            info = json.loads(info_f.read_text()) if info_f.exists() else {}
            segs = clean_vtt(vtts[0].read_text(errors="replace"))
            words = sum(len(s["text"].split()) for s in segs)
            doc = {"creator": CREATOR, "channel": CHANNEL, "video_id": vid,
                   "url": f"https://www.youtube.com/watch?v={vid}", "kind": v["kind"],
                   "title": info.get("title") or v.get("title"),
                   "upload_date": info.get("upload_date"),
                   "duration_s": info.get("duration") or v.get("duration"),
                   "view_count": info.get("view_count") or v.get("view_count"),
                   "segments": segs, "word_count": words}
            (OUT / f"{vid}.json").write_text(json.dumps(doc, ensure_ascii=False))
            failures.pop(vid, None)
            print(f"[{i}/{len(sel)}] ok {vid} {words}w {doc['title'][:50]}", flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    fails.write_text(json.dumps(failures, indent=1))


if __name__ == "__main__":
    main()
