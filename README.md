# Cold Hard Truth Bro

An AI coach panel: local RAG over YouTube transcripts of relationship and life coaches. Ask a question
(or send a screenshot of a chat or profile) and get one answer built from many coaches' principles, next to
a plain "mainstream" answer for comparison. Everything except the final answer runs locally and free.

## Architecture
yt-dlp (subtitles only) -> Ollama qwen2.5:14b extraction -> nomic-embed-text + SQLite index -> Claude answers.

```
collect.py  ->  data/transcripts/<creator>/<id>.json      (subtitles only, gitignored)
extract.py  ->  <kb>/<creator>/<id>.jsonl                 (Ollama, qwen2.5:14b, JSON mode)
index.py    ->  <kb>/index.sqlite                         (nomic-embed-text, float32 BLOB)
ask.py      ->  compact JSON of the best principles       (numpy cosine, filters, per-creator cap)
```

Principles carry a `topic` from a fixed list and a `reach` (`universal`, `dating`, `work`) so a work
question only sees universal and work principles.

## Answer format
1. The move: what to say or do.
2. The full picture: why it works, all angles blended into one explanation.
3. Different approaches: only when the advice is truly opposite, described neutrally as A / B.
4. Honest take: does it fit this situation.
5. Where this differs from mainstream: one honest line.
Every question also gets a mainstream answer written first, with no knowledge base, so the difference is
visible. Likelihood questions get bands (Low / Possible / Concerning / Strong signs), never fake percentages.

## Text Polisher
Paste a draft text and get 2 to 3 rewrites (playful / direct / minimal), each with a one-line reason.
It sharpens your own voice rather than replacing it.

## Public engine / private data
Prompts, rosters, the knowledge base and real eval scenarios live in a separate private repo, found via
`PRIVATE_DIR` (default `../cold-hard-truth-bro-private`). If it does not exist the code falls back to
`examples/`, so a fresh clone runs end to end on the demo data. `scripts/public-guard.sh` is installed as
a pre-push hook and blocks private paths, database/subtitle/transcript files, files over 1 MB and any term
on a denylist kept in the private repo. It fails closed if the denylist is missing.

## Run
Requires Python 3, numpy, and Ollama with `qwen2.5:14b` and `nomic-embed-text` pulled.
```
cp scripts/public-guard.sh .git/hooks/pre-push
python3 index.py                       # embed the demo principles in examples/kb
python3 ask.py "how short should my texts be" --k 5
python3 collect.py <slug>              # slug must exist in creators.json
python3 extract.py <slug> --top 25     # resumable; --rest 25 for the others
python3 index.py && python3 ask.py "query" --topic texting --debug
```
`ask.py` options: `--topic`, `--reach dating|work`, `--k`, `--per-creator-cap`, `--debug`.

## Roadmap
- v1: Claude Code skill
- v2: MCP server, so it works in the Claude app
- v3: public web app with generic coach labels
