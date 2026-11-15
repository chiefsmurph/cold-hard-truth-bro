#!/opt/homebrew/bin/python3
"""Stage 2: extract principles from transcripts with a local Ollama model.
usage: extract.py <creator-slug> [--top N | --rest N] [--limit-chunks N]
Output: <PRIVATE_DIR>/kb/<slug>/<video_id>.jsonl  (resumable)."""
import argparse, json, re, sys, time
from cht_common import DATA, GEN_MODEL, kb_dir, resource, post

TOPICS = "texting first-dates attraction pulling-away tests relationships cheating-trust breakups-exes profiles-apps confidence-frame time-boundaries career-work money-mission friends-family other".split()
REACH = {"universal", "dating", "work"}
WORDS = 1500


def chunks(segs):
    out, cur, n = [], [], 0
    for s in segs:
        cur.append(s); n += len(s["text"].split())
        if n >= WORDS:
            out.append(cur); cur, n = [], 0
    if cur:
        if out and n < WORDS // 3:
            out[-1] += cur
        else:
            out.append(cur)
    return out


def render(seg_list):
    return "\n".join(f"[t={s['t']}] {s['text']}" for s in seg_list)


def call(prompt, text):
    r = post("/api/chat", {"model": GEN_MODEL, "stream": False, "format": "json",
                           "options": {"temperature": 0.2, "num_ctx": 4096},
                           "messages": [{"role": "system", "content": prompt},
                                        {"role": "user", "content": "Chunk:\n" + text}]})
    try:
        return json.loads(r["message"]["content"]).get("principles", [])
    except Exception:
        return []


def clean(p, lo, hi):
    if not isinstance(p, dict) or not str(p.get("principle", "")).strip():
        return None
    topic = p.get("topic") if p.get("topic") in TOPICS else "other"
    reach = p.get("reach") if p.get("reach") in REACH else "dating"
    try:
        t = int(p.get("t"))
    except Exception:
        t = lo
    t = min(max(t, lo), hi)
    q = " ".join(str(p.get("stance_quote", "")).split()[:25])
    return {"principle": str(p["principle"]).strip(), "topic": topic, "reach": reach,
            "stance_quote": q, "t": t}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("creator")
    ap.add_argument("--top", type=int, help="top N videos by view_count")
    ap.add_argument("--rest", type=int, default=0, help="skip the top N, do all the others")
    ap.add_argument("--limit-chunks", type=int, help="stop after N chunks total (timing test)")
    ap.add_argument("--dry", action="store_true", help="with --limit-chunks: do not write output")
    a = ap.parse_args()
    prompt = resource("prompts/extract.md").read_text()
    docs = [json.loads(p.read_text()) for p in (DATA / "transcripts" / a.creator).glob("*.json")]
    docs.sort(key=lambda d: d.get("view_count") or 0, reverse=True)
    docs = docs[:a.top] if a.top else docs[a.rest:]
    out_dir = kb_dir() / a.creator
    out_dir.mkdir(parents=True, exist_ok=True)
    done_chunks = done_pr = 0
    t0 = time.time()
    for vi, d in enumerate(docs, 1):
        f = out_dir / f"{d['video_id']}.jsonl"
        if f.exists() and not a.limit_chunks:
            continue
        lines = []
        for ch in chunks(d["segments"]):
            lo, hi = ch[0]["t"], ch[-1]["t"]
            ts = time.time()
            ps = [c for c in (clean(p, lo, hi) for p in call(prompt, render(ch))[:6]) if c]
            done_chunks += 1
            done_pr += len(ps)
            print(f"[{vi}/{len(docs)}] {d['video_id']} chunk {lo}-{hi}s: {len(ps)} principles, "
                  f"{time.time()-ts:.1f}s (avg {(time.time()-t0)/done_chunks:.1f}s/chunk)", flush=True)
            for c in ps:
                lines.append(json.dumps(dict(creator=a.creator, video_id=d["video_id"],
                             url=f"{d['url']}&t={c['t']}", title=d["title"], **c), ensure_ascii=False))
            if a.limit_chunks and done_chunks >= a.limit_chunks:
                for l in lines: print(l)
                return
        tmp = f.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""))
        tmp.rename(f)  # atomic: a video file exists only when fully done
    print(f"done: {done_chunks} chunks, {done_pr} principles, {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
