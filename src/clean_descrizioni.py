"""Restore inter-word spacing in descrizione text via Gemini 2.5 Flash on Vertex.

Pipeline:

  raw descrizione --> Gemini 2.5 Flash (Pydantic response_schema)
                      --> CleanedText.text
                      --> normalize_for_invariant() check
                      --> accept | retry-once | reject-and-keep-raw

Two complementary guards:

  1. Pydantic `response_schema=CleanedText` forces JSON-shaped output.
  2. A normalize-and-compare invariant rejects any rewording: after
     stripping whitespace and normalizing curly quotes / dashes / NFKC,
     the cleaned text MUST equal the original. Anything else => reject.

Idempotent: skips strings already in the output CSV. Concurrent with a
small thread pool (Vertex tolerates this well).

Env:
  GOOGLE_CLOUD_PROJECT       (required)
  GOOGLE_CLOUD_LOCATION      (default: us-central1)
  ADC via `gcloud auth application-default login`
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
SRC_CSV    = ROOT / "data" / "processed" / "measures_2024.csv"
OUT_CSV    = ROOT / "data" / "processed" / "descrizioni_clean.csv"
REVIEW_CSV = ROOT / "data" / "processed" / "descrizioni_review.csv"

MODEL = "gemini-2.5-flash"

SYSTEM = (
    "You are a careful text-normalisation tool. Input is Italian text "
    "extracted from a PDF that occasionally lost inter-word spaces "
    "(e.g. 'del50%', 'gliinterventi'). Output the same text with the "
    "missing inter-word spaces restored. CRITICAL CONSTRAINTS: do not "
    "change, remove, add, or reorder any non-space character; do not "
    "fix typos; do not translate; do not paraphrase; do not add or "
    "remove punctuation. The only edits allowed are inserting or "
    "collapsing whitespace."
)


class CleanedText(BaseModel):
    text: str = Field(description="The input text with inter-word spaces restored.")


# ---- invariant ----------------------------------------------------------

_PUNCT_MAP = str.maketrans({
    "’": "'", "‘": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_PUNCT_MAP)
    return re.sub(r"\s+", "", s).lower()


def invariant_ok(orig: str, cleaned: str) -> bool:
    return _norm(orig) == _norm(cleaned)


# ---- model call ---------------------------------------------------------

def make_client():
    from google import genai
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        sys.exit("Set GOOGLE_CLOUD_PROJECT (and run `gcloud auth application-default login`).")
    return genai.Client(
        vertexai=True,
        project=project,
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


def call_gemini(client, text: str, *, strict: bool = False) -> str:
    from google.genai import types
    prompt = f"TEXT:\n{text}"
    if strict:
        prompt = (
            "Your previous output failed the invariant check (it changed "
            "non-space characters). Try again, more carefully.\n\n" + prompt
        )
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=CleanedText,
        temperature=0.0,
        max_output_tokens=2048,
    )
    resp = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
    parsed = CleanedText.model_validate_json(resp.text)
    return parsed.text


# ---- driver -------------------------------------------------------------

@dataclass
class Result:
    n: int
    status: str          # "ok" | "retry-ok" | "reject" | "skip"
    orig: str
    cleaned: str
    note: str = ""


def clean_one(client, n: int, orig: str) -> Result:
    if not orig.strip():
        return Result(n, "skip", orig, orig, "empty")
    try:
        out = call_gemini(client, orig)
    except Exception as e:
        return Result(n, "reject", orig, orig, f"api-error: {e!s}"[:200])
    if invariant_ok(orig, out):
        return Result(n, "ok", orig, out)
    try:
        out2 = call_gemini(client, orig, strict=True)
    except Exception as e:
        return Result(n, "reject", orig, orig, f"api-error-retry: {e!s}"[:200])
    if invariant_ok(orig, out2):
        return Result(n, "retry-ok", orig, out2)
    return Result(n, "reject", orig, orig,
                  f"invariant fail twice; len_orig={len(orig)} len_out={len(out2)}")


def load_cache(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {int(r["n"]): r["descrizione_clean"] for r in csv.DictReader(f)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="cap rows for a test run")
    ap.add_argument("--force", action="store_true", help="ignore cache")
    args = ap.parse_args(argv)

    rows = []
    with SRC_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((int(r["n"]), r["descrizione"]))
    if args.limit:
        rows = rows[: args.limit]

    cache = {} if args.force else load_cache(OUT_CSV)
    todo = [(n, t) for n, t in rows if n not in cache]
    print(f"{len(rows)} total | {len(cache)} cached | {len(todo)} to process")

    client = make_client()
    results: list[Result] = []
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(clean_one, client, n, t): n for n, t in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            if i % 25 == 0 or i == len(futs):
                rate = i / max(time.time() - started, 1e-6)
                print(f"  {i}/{len(futs)} ({rate:.1f}/s)")

    # merge cache + new ok/retry-ok; rejects fall back to original
    cleaned_map = dict(cache)
    rejects = []
    for r in results:
        if r.status in ("ok", "retry-ok"):
            cleaned_map[r.n] = r.cleaned
        else:
            cleaned_map[r.n] = r.orig
            if r.status == "reject":
                rejects.append(r)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n", "descrizione_clean"])
        for n in sorted(cleaned_map):
            w.writerow([n, cleaned_map[n]])

    if rejects:
        with REVIEW_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["n", "note", "orig", "model_output"])
            for r in rejects:
                w.writerow([r.n, r.note, r.orig, r.cleaned])

    from collections import Counter
    c = Counter(r.status for r in results)
    print(f"\nstatus: {dict(c)}")
    print(f"cleaned rows total: {len(cleaned_map)}")
    if rejects:
        print(f"rejects logged -> {REVIEW_CSV}")


if __name__ == "__main__":
    main()
