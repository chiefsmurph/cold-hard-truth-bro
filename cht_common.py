"""Shared helpers: locate the private repo (PRIVATE_DIR) and fall back to examples/."""
import json, os
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
GEN_MODEL = os.environ.get("CHT_GEN_MODEL", "qwen2.5:14b")
EMBED_MODEL = "nomic-embed-text"


def private_dir():
    d = Path(os.environ.get("PRIVATE_DIR", HERE.parent / "cold-hard-truth-bro-private")).expanduser()
    return d if d.is_dir() else None


def resource(rel):
    """Return a file from the private repo if present, else from examples/."""
    p = private_dir()
    if p and (p / rel).exists():
        return p / rel
    return HERE / "examples" / rel


def kb_dir():
    p = private_dir()
    return (p / "kb") if p else (HERE / "examples" / "kb")


def creators():
    return json.loads(resource("creators.json").read_text())


def post(path, payload, timeout=600):
    import urllib.request
    req = urllib.request.Request(OLLAMA + path, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
