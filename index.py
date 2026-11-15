#!/opt/homebrew/bin/python3
"""Stage 3: embed principles (nomic-embed-text) into <kb>/index.sqlite. Incremental by id hash."""
import hashlib, json, sqlite3
import numpy as np
from cht_common import kb_dir, post, EMBED_MODEL

SCHEMA = """CREATE TABLE IF NOT EXISTS principles(
 id TEXT PRIMARY KEY, creator TEXT, video_id TEXT, url TEXT, title TEXT, principle TEXT,
 topic TEXT, reach TEXT, quote TEXT, t INTEGER, emb BLOB)"""


def main():
    kb = kb_dir()
    db = sqlite3.connect(kb / "index.sqlite")
    db.execute(SCHEMA)
    have = {r[0] for r in db.execute("SELECT id FROM principles")}
    new = []
    for f in sorted(kb.glob("*/*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            i = hashlib.sha1(f"{r['video_id']}|{r['t']}|{r['principle']}".encode()).hexdigest()[:16]
            if i not in have:
                new.append((i, r))
    for s in range(0, len(new), 64):
        batch = new[s:s + 64]
        embs = post("/api/embed", {"model": EMBED_MODEL, "input": ["search_document: " + r["principle"] for _, r in batch]})["embeddings"]
        for (i, r), e in zip(batch, embs):
            v = np.array(e, dtype=np.float32)
            v /= (np.linalg.norm(v) or 1)
            db.execute("INSERT OR IGNORE INTO principles VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (i, r["creator"], r["video_id"], r["url"], r["title"], r["principle"], r["topic"],
                        r["reach"], r.get("stance_quote", ""), r["t"], v.tobytes()))
        db.commit()
    total = db.execute("SELECT COUNT(*) FROM principles").fetchone()[0]
    print(f"indexed {len(new)} new, {total} total")


if __name__ == "__main__":
    main()
