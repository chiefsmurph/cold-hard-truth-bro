#!/usr/bin/env python3
"""Attitudes layer: extract what a speaker expresses or signals about people, groups and issues (banter, jabs and
asides included), separately from the actionable principles. Claude Haiku 5.5 via the Message Batches API (50% off).
usage: extract_attitudes.py <creator-slug> [--out DIR] [--limit-videos N] [--budget USD] [--no-wait]
Output: <kb>/<slug>/attitudes/<video_id>.jsonl. Resumable: batch ids tracked in data/attitude-batches.json; a rerun
fetches pending results before submitting anything new. --budget is a hard USD cap across all runs
(data/attitude-spend.json); a run that would exceed it aborts before submitting. Key: env or ANTHROPIC_ENV_FILE."""
import argparse, json, sys, time
from pathlib import Path
from cht_common import DATA, kb_dir, resource
from extract import chunks, render
import extract_claude as ec

TOPICS = ("sexuality-orientation gender-roles masculinity-femininity feminism marriage-divorce-law family-parenting "
          "religion race-ethnicity politics-left-right class-money-status body-looks-fitness age-gaps "
          "immigration-culture media-celebrities health-diet-claims other-cultural").split()
TONES = ["serious", "joke", "criticism", "praise", "neutral"]
EXPL = ["explicit", "implied"]
STATE, SPEND = DATA / "attitude-batches.json", DATA / "attitude-spend.json"
ec.SPEND = SPEND   # reuse cost/spend helpers with our own ledger
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["attitudes"], "properties": {
    "attitudes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["topic", "stance", "quote", "t", "tone", "explicitness", "target"], "properties": {
            "topic": {"type": "string", "enum": TOPICS}, "stance": {"type": "string"}, "quote": {"type": "string"},
            "t": {"type": "integer"}, "tone": {"type": "string", "enum": TONES},
            "explicitness": {"type": "string", "enum": EXPL}, "target": {"type": "string"}}}}}}


def clean(a, lo, hi, hay):
    """Validate one record; None if unusable. The quote must appear verbatim (normalised) in the chunk."""
    if not isinstance(a, dict) or not str(a.get("stance", "")).strip():
        return None
    q = " ".join(str(a.get("quote", "")).split())
    if not ec.norm(q) or ec.norm(q) not in hay:
        return "nonverbatim"
    if len(q) > 300:
        q = q[:300].rsplit(" ", 1)[0]
    try:
        t = int(a.get("t"))
    except Exception:
        t = lo
    return {"topic": a.get("topic") if a.get("topic") in TOPICS else "other-cultural", "stance": str(a["stance"]).strip(),
            "quote": q, "t": min(max(t, lo), hi), "tone": a.get("tone") if a.get("tone") in TONES else "neutral",
            "explicitness": a.get("explicitness") if a.get("explicitness") in EXPL else "implied",
            "target": str(a.get("target", "")).strip()}


def process(client, bid, rec, out_dir):
    docs = {d["video_id"]: d for d in (json.loads(p.read_text())
            for p in (DATA / "transcripts" / rec["slug"]).glob("*.json")) if d["video_id"] in rec["videos"]}
    got, inp, outp, errors = {}, 0, 0, 0
    for r in client.messages.batches.results(bid):
        vid, idx = rec["map"][int(r.custom_id[1:])]
        if r.result.type != "succeeded":
            errors += 1; print(f"  {r.custom_id}: {r.result.type}", flush=True); continue
        m = r.result.message
        inp += m.usage.input_tokens; outp += m.usage.output_tokens
        text = next((b.text for b in m.content if b.type == "text"), "")
        try:
            got[(vid, int(idx))] = json.loads(text).get("attitudes", [])
        except Exception:
            errors += 1; print(f"  {r.custom_id}: unparseable ({m.stop_reason})", flush=True)
    kept = dropped = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for vid, d in docs.items():
        chs = chunks(d["segments"])
        if any((vid, i) not in got for i in range(len(chs))):
            continue  # incomplete video: not written, resubmitted next run
        lines = []
        for i, ch in enumerate(chs):
            hay = ec.norm(" ".join(s["text"] for s in ch))
            for a in got[(vid, i)][:8]:
                c = clean(a, ch[0]["t"], ch[-1]["t"], hay)
                if c == "nonverbatim" or c is None:
                    dropped += 1; continue
                kept += 1
                lines.append(json.dumps(dict(creator=rec["slug"], video_id=vid, url=f"{d['url']}&t={c['t']}",
                             title=d["title"], **c, extractor=ec.MODEL), ensure_ascii=False))
        f = out_dir / f"{vid}.jsonl"
        tmp = f.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else "")); tmp.rename(f)
    return inp, outp, kept, dropped, errors


def fetch_pending(client, slug, wait):
    st = ec.jload(STATE, {})
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
        inp, outp, kept, dropped, errors = process(client, bid, rec, Path(rec["out"]) / rec["slug"] / "attitudes")
        ec.add_spend(inp, outp, kept, dropped)
        rec.update(processed=True, input_tokens=inp, output_tokens=outp, kept=kept, dropped_nonverbatim=dropped,
                   errors=errors, usd=round(ec.cost(inp, outp), 4))
        ec.jsave(STATE, st)
        print(f"batch {bid} done: kept {kept}, dropped non-verbatim {dropped}, errors {errors}, in {inp} out {outp} "
              f"tok = ${ec.cost(inp, outp):.4f} (total spend ${ec.spent():.4f})", flush=True)
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("creator")
    ap.add_argument("--out", help="output kb dir (default: <PRIVATE_DIR>/kb)")
    ap.add_argument("--limit-videos", type=int)
    ap.add_argument("--budget", type=float, default=10.0, help="hard USD cap across all runs of this script")
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()
    ec.load_key()
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    client = anthropic.Anthropic()
    out_dir = (Path(a.out).expanduser() if a.out else kb_dir()) / a.creator / "attitudes"
    st = fetch_pending(client, a.creator, wait=False)
    inflight = {v for r in st.values() if r["slug"] == a.creator and not r.get("processed") for v in r["videos"]}
    if ec.spent() > a.budget:
        sys.exit(f"BUDGET: spent ${ec.spent():.2f} > cap ${a.budget:.2f}")
    prompt = resource("prompts/attitudes.md").read_text()
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
                model=ec.MODEL, max_tokens=ec.MAX_TOKENS, system=prompt,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": text}])))
    if reqs:
        proj = ec.spent() + ec.cost(est_in, len(reqs) * 800)
        if proj > a.budget:
            sys.exit(f"BUDGET: projected ${proj:.2f} > cap ${a.budget:.2f}; not submitting {a.creator}")
        batch = client.messages.batches.create(requests=reqs)
        st = ec.jload(STATE, {})
        st[batch.id] = dict(slug=a.creator, out=str(out_dir.parent.parent), videos=[d["video_id"] for d in docs],
                            n_requests=len(reqs), map=cmap, created=time.strftime("%F %T"), processed=False)
        ec.jsave(STATE, st)
        print(f"submitted batch {batch.id}: {len(docs)} videos, {len(reqs)} chunks, projected ${proj:.2f}", flush=True)
    elif not inflight:
        print(f"{a.creator}: nothing to do"); return
    fetch_pending(client, a.creator, wait=not a.no_wait)
    if ec.spent() > a.budget:
        sys.exit(f"BUDGET exceeded: ${ec.spent():.2f} > ${a.budget:.2f}")


if __name__ == "__main__":
    main()
