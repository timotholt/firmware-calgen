"""Optional AI step: classify unexplained constants found by the audit.

The deterministic scanner finds every number; this module asks a language
model what each one *is* (category, units, typed vs derived, which rule it
corresponds to) so a reviewer starts from a draft instead of a blank page.

Design rules:

* The AI never writes firmware and never changes a spec. Its output is a draft
  for human review.
* Every answer is validated against a JSON schema; invalid answers are counted
  as failures, never silently accepted.
* Backends are interchangeable: ``replay`` (default; recorded responses, no
  network, no key), ``openai``, ``anthropic``, ``none``. On controlled data,
  use a local model behind the same interface or ``none``.
* The answer key used for evaluation is never read here.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from calgen.audit import Candidate
from calgen.spec import Rules

CATEGORIES = [
    "sense_full_scale",
    "sense_scale_factor",
    "trip_limit",
    "protection_threshold",
    "setpoint",
    "timing",
    "control_gain",
    "battery",
    "pin_map",
    "comms_or_buffer",
    "version_or_id",
    "other",
]
CONFIDENCE = ["low", "medium", "high"]

SYSTEM_PROMPT = """You review legacy embedded C firmware for an uninterruptible power supply.
For every numeric constant listed, say what it is. Use the file text for context
(names, comments, how the value is used). Be literal: a UART baud rate is
comms_or_buffer, not timing. If a constant is the same physical quantity as one
of the listed spec rules (after an obvious unit conversion), give that rule id;
otherwise null. "typed" is true when the value is a hand-typed literal and false
when it is computed from other macros. Units: use one of V, A, Hz, s, ms, us,
counts, ratio, V/count, A/count, baud, bytes, none. Comments in the code may be
wrong; trust the value and how it is used over the comment.

Categories:
- sense_full_scale: the physical value (V or A) a sensor channel reads at full scale, or the converter's full-scale count
- sense_scale_factor: physical units per ADC count
- trip_limit: a level that trips protection (shutdown, bypass, hardware comparator), including comparator codes for it
- protection_threshold: an operating-window or band edge (input transfer limits, output regulation band) that is not itself a trip
- setpoint: a value the controller regulates to
- timing: clock, PWM period, dead time, delays, time windows
- control_gain: control-loop gains and coefficients
- battery: battery string voltages and battery thresholds
- pin_map: GPIO and peripheral pin assignments
- comms_or_buffer: baud rates, buffer and log sizes, retry counts
- version_or_id: firmware versions, model or product identifiers
- other: anything else, including product ratings that are not regulated or tripped on"""


def output_schema(rule_ids: list[str], ids: list[str] | None = None) -> dict:
    id_schema: dict = {"type": "string", "enum": ids} if ids else {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": id_schema,
                        "category": {"type": "string", "enum": CATEGORIES},
                        "units": {"type": "string"},
                        "typed": {"type": "boolean"},
                        "maps_to_rule": {"anyOf": [{"type": "string", "enum": rule_ids}, {"type": "null"}]},
                        "confidence": {"type": "string", "enum": CONFIDENCE},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "category", "units", "typed", "maps_to_rule", "confidence", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def candidate_id(c: Candidate, index: int) -> str:
    """Short per-file id; the schema restricts answers to exactly these ids."""
    return f"c{index + 1}"


def build_prompt(file_text: str, file_name: str, cands: list[Candidate], rules: Rules) -> tuple[str, list[str]]:
    numbered = "\n".join(f"{i:4d}| {line}" for i, line in enumerate(file_text.splitlines(), start=1))
    ids = [candidate_id(c, i) for i, c in enumerate(cands)]
    rule_lines = "\n".join(f"- {r.id} ({r.unit}): {r.describe}" for r in rules.constants if r.kind == "numeric")
    cand_lines = "\n".join(f"- id={cid} line={c.line} symbol={c.symbol} literal={c.literal}" for cid, c in zip(ids, cands))
    prompt = (
        f"Spec rules (rule id, unit, meaning):\n{rule_lines}\n\n"
        f"Categories: {', '.join(CATEGORIES)}\n\n"
        f"File {file_name}:\n{numbered}\n\n"
        f"Classify each of these constants (one item per id, same ids):\n{cand_lines}\n"
    )
    return prompt, ids


@dataclass
class Classification:
    id: str
    category: str
    units: str
    typed: bool
    maps_to_rule: str | None
    confidence: str
    reason: str


@dataclass
class FileResult:
    file: str
    prompt_sha: str
    items: list[Classification]
    invalid: list[str]  # ids missing or schema-invalid
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    raw: dict = field(default_factory=dict)


def validate(raw: dict, ids: list[str], rule_ids: list[str]) -> tuple[list[Classification], list[str]]:
    good: dict[str, Classification] = {}
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        try:
            cid = str(item["id"])
            ok = (
                cid in ids
                and item["category"] in CATEGORIES
                and isinstance(item["typed"], bool)
                and (item["maps_to_rule"] is None or item["maps_to_rule"] in rule_ids)
                and item["confidence"] in CONFIDENCE
                and isinstance(item["units"], str)
            )
        except (KeyError, TypeError):
            continue
        if ok and cid not in good:
            good[cid] = Classification(
                cid, item["category"], item["units"], item["typed"], item["maps_to_rule"], item["confidence"], str(item.get("reason", ""))
            )
    invalid = [i for i in ids if i not in good]
    return [good[i] for i in ids if i in good], invalid


class Backend(Protocol):
    name: str
    model: str

    def complete(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        """Return (parsed JSON, input tokens, output tokens)."""
        ...


class NoBackend:
    name, model = "none", "none"

    def complete(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        return {"items": []}, 0, 0


class OpenAIBackend:
    name = "openai"

    def __init__(self, model: str):
        from openai import OpenAI

        self.model = model
        self.client = OpenAI()

    def complete(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {"name": "classification", "schema": schema, "strict": True}},
        )
        text = resp.choices[0].message.content or "{}"
        usage = resp.usage
        return json.loads(text), usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str, effort: str = "low"):
        import anthropic

        self.model = model
        self.effort = effort
        self.client = anthropic.Anthropic()

    def complete(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            return {"items": []}, resp.usage.input_tokens, resp.usage.output_tokens
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        return json.loads(text), resp.usage.input_tokens, resp.usage.output_tokens


class ReplayBackend:
    """Serves recorded responses; refuses if the prompt changed since recording."""

    name = "replay"

    def __init__(self, recording: Path):
        self.path = recording
        self.data = json.loads(recording.read_text(encoding="utf-8"))
        self.model = self.data["model"]

    def complete(self, system: str, prompt: str, schema: dict) -> tuple[dict, int, int]:
        sha = prompt_sha(system, prompt, schema)
        entry = self.data["responses"].get(sha)
        if entry is None:
            raise LookupError(f"{self.path.name}: no recording for this prompt (prompt or rules changed; re-record)")
        self.last_latency = entry.get("latency_s") or 0.0  # report the live run's latency, not replay's
        return entry["raw"], entry["input_tokens"], entry["output_tokens"]


def prompt_sha(system: str, prompt: str, schema: dict) -> str:
    h = hashlib.sha256()
    for part in (system, prompt, json.dumps(schema, sort_keys=True)):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()


def classify(root: Path, candidates: list[Candidate], rules: Rules, backend: Backend) -> list[FileResult]:
    """One model call per file, so the model sees each constant in context."""
    rule_ids = [r.id for r in rules.constants if r.kind == "numeric"]
    out = []
    for file in sorted({c.file for c in candidates}):
        cands = [c for c in candidates if c.file == file]
        prompt, ids = build_prompt((root / file).read_text(encoding="utf-8"), file, cands, rules)
        schema = output_schema(rule_ids, ids)
        start = time.monotonic()
        raw, tin, tout = backend.complete(SYSTEM_PROMPT, prompt, schema)
        latency = getattr(backend, "last_latency", None) or (time.monotonic() - start)
        items, invalid = validate(raw, ids, rule_ids)
        out.append(FileResult(file, prompt_sha(SYSTEM_PROMPT, prompt, schema), items, invalid, tin, tout, latency, raw))
    return out


def record(results: list[FileResult], backend: Backend, path: Path, recorded_latency: bool = True) -> None:
    """Save responses so ReplayBackend can serve them offline (CI, demo site)."""
    data = {
        "backend": backend.name,
        "model": backend.model,
        "responses": {
            r.prompt_sha: {
                "file": r.file,
                "raw": r.raw,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "latency_s": round(r.latency_s, 2) if recorded_latency else None,
            }
            for r in results
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
