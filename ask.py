#!/opt/homebrew/bin/python3
"""Stage 4: retrieve the best principles for a query. Prints compact JSON."""
import argparse, json, sqlite3
import numpy as np
from cht_common import kb_dir, post, EMBED_MODEL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--topic")
    ap.add_argument("--reach", choices=["dating", "work"])
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--per-creator-cap", type=int, default=6)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(kb_dir() / "index.sqlite")
    where, args = [], []
    if a.topic:
        where.append("topic=?"); args.append(a.topic)
    if a.reach == "work":
        where.append("reach IN ('universal','work')")
    elif a.reach == "dating":
        where.append("reach IN ('universal','dating')")
    rows = db.execute("SELECT id,creator,url,title,principle,topic,reach,quote,t,emb FROM principles"
                      + (" WHERE " + " AND ".join(where) if where else ""), args).fetchall()
    if not rows:
        print("[]"); return
    qv = np.array(post("/api/embed", {"model": EMBED_MODEL, "input": ["search_query: " + a.query]})["embeddings"][0], dtype=np.float32)
    qv /= np.linalg.norm(qv) or 1
    M = np.vstack([np.frombuffer(r[9], dtype=np.float32) for r in rows])
    order = np.argsort(-(M @ qv))
    out, per = [], {}
    for i in order:
        r = rows[i]
        if per.get(r[1], 0) >= a.per_creator_cap:
            continue
        per[r[1]] = per.get(r[1], 0) + 1
        d = {"principle": r[4], "topic": r[5], "reach": r[6], "quote": r[7]}
        if a.debug:
            d.update(creator=r[1], url=r[2], title=r[3])
        out.append(d)
        if len(out) >= a.k:
            break
    print(json.dumps(out, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    main()
