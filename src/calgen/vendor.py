"""Fetch the site's third-party assets once, verify checksums, and stage them.

The published site makes no network requests: KaTeX (math) and Pyodide (Python
in the browser) are served from the site itself. This module downloads pinned
versions, verifies each against a published checksum, and extracts only the
files the site uses. Downloads are cached in ``vendor/`` (gitignored).
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PYODIDE = "0.27.7"


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    algo: str  # sha256 | sha512 (npm integrity, base64)
    digest: str
    source_of_digest: str


ASSETS = [
    Asset(
        "katex-0.16.22.tgz",
        "https://registry.npmjs.org/katex/-/katex-0.16.22.tgz",
        "sha512",
        "XCHRdUw4lf3SKBaJe4EvgqIuWwkPSo9XoeO8GjQW94Bp7TWv9hNhzZjZ+OH9yf1UmLygb7DIT5GSFQiyt16zYg==",
        "npm registry dist.integrity",
    ),
    Asset(
        f"pyodide-core-{PYODIDE}.tar.bz2",
        f"https://github.com/pyodide/pyodide/releases/download/{PYODIDE}/pyodide-core-{PYODIDE}.tar.bz2",
        "sha256",
        "9bc8f127db6c590b191b9aee754022cb41b1a36c7bac233776c11c5ecb541be8",
        "GitHub release asset digest",
    ),
    Asset(
        "pyyaml-6.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl",
        f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE}/full/pyyaml-6.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl",
        "sha256",
        "444d034ede13ca0a2961a1215838fb7d4cf6fa98ba7fe5e2a09e5063180af2bf",
        f"pyodide-lock.json in pyodide-core-{PYODIDE}",
    ),
]

PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]


def _digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    h.update(path.read_bytes())
    return base64.b64encode(h.digest()).decode() if algo == "sha512" else h.hexdigest()


def fetch(cache: Path, download: bool = True) -> dict[str, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for a in ASSETS:
        path = cache / a.name
        if not path.exists():
            if not download:
                raise FileNotFoundError(f"{path} missing; run `calgen vendor`")
            with urllib.request.urlopen(a.url, timeout=120) as r, path.open("wb") as f:  # noqa: S310 - pinned https URLs
                shutil.copyfileobj(r, f)
        got = _digest(path, a.algo)
        if got != a.digest:
            path.unlink()
            raise ValueError(f"{a.name}: {a.algo} mismatch (got {got}, want {a.digest} from {a.source_of_digest})")
        out[a.name] = path
    return out


def stage(cache: Path, assets_dir: Path, download: bool = True) -> None:
    """Extract verified assets into <site>/assets/{katex,pyodide}."""
    files = fetch(cache, download)
    katex_dir = assets_dir / "katex"
    katex_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(files["katex-0.16.22.tgz"]) as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            rel = m.name.removeprefix("package/dist/")
            if rel == m.name:
                if m.name == "package/LICENSE":
                    (katex_dir / "LICENSE").write_bytes(t.extractfile(m).read())
                continue
            if rel in ("katex.min.js", "katex.min.css") or (rel.startswith("fonts/") and rel.endswith(".woff2")):
                dest = katex_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(t.extractfile(m).read())
    py_dir = assets_dir / "pyodide"
    py_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(files[f"pyodide-core-{PYODIDE}.tar.bz2"]) as t:
        for name in PYODIDE_FILES + ["LICENSE"]:
            try:
                m = t.getmember(f"pyodide/{name}")
            except KeyError:
                continue
            (py_dir / name).write_bytes(t.extractfile(m).read())
    whl = ASSETS[2].name
    shutil.copyfile(files[whl], py_dir / whl)
