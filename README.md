# Cold Hard Truth Bro

A personal RAG "coach panel". Transcripts of advice videos go through a local LLM that distills each
chunk into short, tagged principles. The principles are embedded into a SQLite index. At question time
a retrieval step returns about 15 compact lines, and an assistant (Claude Code skill) writes the answer.
Everything except the final answer runs locally and free.

```
collect.py  ->  data/transcripts/<creator>/<id>.json      (subtitles only, gitignored)
extract.py  ->  <kb>/<creator>/<id>.jsonl                 (Ollama, qwen2.5:14b, JSON mode)
index.py    ->  <kb>/index.sqlite                         (nomic-embed-text, float32 BLOB)
ask.py      ->  compact JSON of the best principles       (numpy cosine, filters, per-creator cap)
```

Principles carry a `topic` from a fixed list and a `reach` (`universal`, `dating`, `work`) so a work
question only sees universal and work principles.

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
