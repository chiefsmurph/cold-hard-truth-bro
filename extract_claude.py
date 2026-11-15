#!/usr/bin/env python3
"""Stage 2 (Claude): extract principles with Claude Haiku 5.5 via the Message Batches API (50% off).
usage: extract_claude.py <creator-slug> [--out DIR] [--limit-videos N] [--budget USD] [--no-wait]
Same output as extract.py (<out>/<slug>/<video_id>.jsonl) plus "extractor". Resumable: submitted batch ids are
tracked in data/claude-batches.json; a rerun fetches pending results before submitting anything new.
Needs ANTHROPIC_API_KEY (env, or ANTHROPIC_ENV_FILE=<path to a .env>); the key is never printed or stored."""
import argparse, json, os, re, sys, time
from pathlib import Path
from cht_common import DATA, kb_dir, resource
from extract import chunks, render, clean

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4000
PRICE_IN, PRICE_OUT, BATCH = 0.10, 0.50, 0.5      # USD per 1M tokens, x0.5 for batches
STATE, SPEND = DATA / "claude-batches.json", DATA / "claude-spend.json"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["principles"], "properties": {
    "principles": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["principle", "topic", "reach", "stance_quote", "t"], "properties": {
            "principle": {"type": "string"}, "topic": {"type": "string"}, "reach": {"type": "string"},
            "stance_quote": {"type": "string"}, "t": {"type": "integer"}}}}}}


def load_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    f = os.environ.get("ANTHROPIC_ENV_FILE")
    if f and Path(f).expanduser().exists():
        for line in Path(f).expanduser().read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*)", line)
            if m:
                os.environ["ANTHROPIC_API_KEY"] = m.group(1).strip().strip("'\"")
                return
    sys.exit("ANTHROPIC_API_KEY not set")


def jload(p, default):
    return json.loads(p.read_text()) if p.exists() else default


def jsave(p, obj):
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(obj, indent=1)); tmp.rename(p)


def norm(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def cost(inp, out):
    return (inp * PRICE_IN + out * PRICE_OUT) / 1e6 * BATCH


def spent():
    return jload(SPEND, {}).get("usd", 0.0)


def add_spend(inp, out, kept, dropped):
    s = jload(SPEND, {"usd": 0.0, "input_tokens": 0, "output_tokens": 0, "kept": 0, "dropped_nonverbatim": 0})
    s["input_tokens"] += inp; s["output_tokens"] += out
    s["kept"] += kept; s["dropped_nonverbatim"] += dropped
    s["usd"] = round(cost(s["input_tokens"], s["output_tokens"]), 6)
    jsave(SPEND, s)


def process(client, bid, rec, out_dir):
    """Fetch an ended batch, validate, write per-video files. Returns (inp, out, kept, dropped, errors)."""
    docs = {d["video_id"]: d for d in (json.loads(p.read_text())
            for p in (DATA / "transcripts" / rec["slug"]).glob("*.json")) if d["video_id"] in rec["videos"]}
    got, inp, outp, errors = {}, 0, 0, 0
    for r in client.messages.batches.results(bid):
        vid, idx = rec["map"][int(r.custom_id[1:])]   # API custom_id allows only [A-Za-z0-9_-]{1,64}: "c<n>" -> map
        if r.result.type != "succeeded":
            errors += 1; print(f"  {r.custom_id}: {r.result.type}", flush=True); continue
        m = r.result.message
        inp += m.usage.input_tokens; outp += m.usage.output_tokens
        text = next((b.text for b in m.content if b.type == "text"), "")
        try:
            got[(vid, int(idx))] = json.loads(text).get("principles", [])
        except Exception:
            errors += 1; print(f"  {r.custom_id}: unparseable ({m.stop_reason})", flush=True)
    kept = dropped = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for vid, d in docs.items():
        chs = chunks(d["segments"])
        if any((vid, i) not in got for i in range(len(chs))):
            continue  # incomplete video: not written, resubmitted on next run
        lines = []
        for i, ch in enumerate(chs):
            lo, hi = ch[0]["t"], ch[-1]["t"]
            hay = norm(" ".join(s["text"] for s in ch))
            for p in got[(vid, i)][:6]:
                if not isinstance(p, dict) or not norm(str(p.get("stance_quote", ""))) or \
                        norm(str(p["stance_quote"])) not in hay:
                    dropped += 1; continue
                c = clean(p, lo, hi)
                if not c:
                    continue
                kept += 1
                lines.append(json.dumps(dict(creator=rec["slug"], video_id=vid, url=f"{d['url']}&t={c['t']}",
                             title=d["title"], **c, extractor=MODEL), ensure_ascii=False))
        f = out_dir / f"{vid}.jsonl"
        tmp = f.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else "")); tmp.rename(f)
    return inp, outp, kept, dropped, errors


def fetch_pending(client, slug, wait):
    st = jload(STATE, {})
    for bid, rec in st.items():
        if rec["slug"] != slug or rec.get("processed"):
            continue
        while True:
            b = client.messages.batches.retrieve(bid)
            if b.processing_status == "ended":
                break
            print(f"batch {bid}: {b.processing_status}, processing={b.request_counts.processing}", flush=True)
            if not wait:
                break
            time.sleep(30)
        if b.processing_status != "ended":
            continue
        inp, outp, kept, dropped, errors = process(client, bid, rec, Path(rec["out"]) / rec["slug"])
        add_spend(inp, outp, kept, dropped)
        rec.update(processed=True, input_tokens=inp, output_tokens=outp, kept=kept,
                   dropped_nonverbatim=dropped, errors=errors, usd=round(cost(inp, outp), 4))
        jsave(STATE, st)
        print(f"batch {bid} done: kept {kept}, dropped non-verbatim {dropped}, errors {errors}, "
              f"in {inp} out {outp} tok = ${cost(inp, outp):.4f} (total spend ${spent():.4f})", flush=True)
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("creator")
    ap.add_argument("--out", help="output kb dir (default: <PRIVATE_DIR>/kb)")
    ap.add_argument("--limit-videos", type=int)
    ap.add_argument("--budget", type=float, default=15.0, help="hard USD cap across all runs")
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()
    load_key()
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    client = anthropic.Anthropic()
    out_dir = (Path(a.out).expanduser() if a.out else kb_dir()) / a.creator
    st = fetch_pending(client, a.creator, wait=False)
    inflight = {v for r in st.values() if r["slug"] == a.creator and not r.get("processed") for v in r["videos"]}
    prompt = resource("prompts/extract.md").read_text()
    docs = [json.loads(p.read_text()) for p in (DATA / "transcripts" / a.creator).glob("*.json")]
    docs.sort(key=lambda d: d.get("view_count") or 0, reverse=True)
    docs = [d for d in docs if not (out_dir / f"{d['video_id']}.jsonl").exists() and d["video_id"] not in inflight]
    if a.limit_videos:
        docs = docs[:a.limit_videos]
    reqs, est_in, cmap = [], 0, []
    for d in docs:
        for i, ch in enumerate(chunks(d["segments"])):
            text = "Chunk:\n" + render(ch)
            est_in += (len(prompt) + len(text)) // 3
            cmap.append([d["video_id"], i])
            reqs.append(Request(custom_id=f"c{len(cmap) - 1}", params=MessageCreateParamsNonStreaming(
                model=MODEL, max_tokens=MAX_TOKENS, system=prompt,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": text}])))
    if reqs:
        proj = spent() + cost(est_in, len(reqs) * 1500)   # generous output estimate (incl. thinking)
        if proj > a.budget:
            sys.exit(f"BUDGET: projected ${proj:.2f} > cap ${a.budget:.2f}; not submitting {a.creator}")
        batch = client.messages.batches.create(requests=reqs)
        st = jload(STATE, {})
        st[batch.id] = dict(slug=a.creator, out=str(out_dir.parent), videos=[d["video_id"] for d in docs],
                            n_requests=len(reqs), map=cmap, created=time.strftime("%F %T"), processed=False)
        jsave(STATE, st)
        print(f"submitted batch {batch.id}: {len(docs)} videos, {len(reqs)} chunks, projected ${proj:.2f}", flush=True)
    elif not inflight:
        print(f"{a.creator}: nothing to do"); return
    fetch_pending(client, a.creator, wait=not a.no_wait)


if __name__ == "__main__":
    main()
