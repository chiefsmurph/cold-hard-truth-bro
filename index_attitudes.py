#!/opt/homebrew/bin/python3
"""Embed attitudes (nomic-embed-text) into the `attitudes` table of <kb>/index.sqlite. Incremental by id hash.
Separate from the principles table. Embeds "stance + quote" so slangy remarks are retrievable by topic or wording."""
import hashlib, json, sqlite3
import numpy as np
from cht_common import kb_dir, post, EMBED_MODEL

SCHEMA = """CREATE TABLE IF NOT EXISTS attitudes(
 id TEXT PRIMARY KEY, creator TEXT, video_id TEXT, url TEXT, title TEXT, topic TEXT, stance TEXT, quote TEXT,
 t INTEGER, tone TEXT, explicitness TEXT, target TEXT, emb BLOB)"""


def main():
    kb = kb_dir()
    db = sqlite3.connect(kb / "index.sqlite")
    db.execute(SCHEMA)
    have = {r[0] for r in db.execute("SELECT id FROM attitudes")}
    new = []
    for f in sorted(kb.glob("*/attitudes/*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            i = hashlib.sha1(f"{r['video_id']}|{r['t']}|{r['stance']}".encode()).hexdigest()[:16]
            if i not in have:
                have.add(i); new.append((i, r))
    for s in range(0, len(new), 64):
        batch = new[s:s + 64]
        embs = post("/api/embed", {"model": EMBED_MODEL, "input": [
            f"search_document: {r['stance']} {r['target']}. \"{r['quote'][:200]}\"" for _, r in batch]})["embeddings"]
        for (i, r), e in zip(batch, embs):
            v = np.array(e, dtype=np.float32)
            v /= (np.linalg.norm(v) or 1)
            db.execute("INSERT OR IGNORE INTO attitudes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (i, r["creator"], r["video_id"], r["url"], r["title"], r["topic"], r["stance"], r["quote"],
                        r["t"], r["tone"], r["explicitness"], r["target"], v.tobytes()))
        db.commit()
    total = db.execute("SELECT COUNT(*) FROM attitudes").fetchone()[0]
    print(f"indexed {len(new)} new attitudes, {total} total")


if __name__ == "__main__":
    main()
