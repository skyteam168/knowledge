"""Export live「真实模型基线」cases with document titles (not UUIDs)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/fixtures/eval_baseline_live.jsonl"
DATASET_ID = "1d4f1d499f924662a99f91077b85f288"


def _psql(sql: str) -> str:
    return subprocess.check_output(
        ["docker", "exec", "ekb-postgres-1", "psql", "-U", "ekb", "-d", "ekb", "-t", "-A", "-c", sql],
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> None:
    raw = _psql(
        f"""
SELECT json_agg(row_to_json(t) ORDER BY ord) FROM (
  SELECT row_number() OVER (ORDER BY c.created_at, c.id) AS ord,
         c.question, c.reference_answer, c.expected_document_ids, c.tags
  FROM eval_cases c
  WHERE c.dataset_id='{DATASET_ID}'
) t;
"""
    ).strip()
    cases = json.loads(raw)
    titles: dict[str, str] = {}
    for line in _psql("SELECT id || E'\\t' || title FROM documents WHERE deleted_at IS NULL;").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        doc_id, title = line.split("\t", 1)
        titles[doc_id] = title

    rows: list[dict[str, object]] = []
    for c in cases:
        ids = c.get("expected_document_ids") or []
        missing = [i for i in ids if i not in titles]
        if missing:
            raise SystemExit(f"missing documents for ids: {missing}")
        exp_titles = [titles[i] for i in ids]
        kind = "ood" if not ids else "answerable"
        tags = list(c.get("tags") or [])
        if "baseline" not in tags:
            tags = ["baseline", *tags]
        rows.append(
            {
                "id": f"baseline-{int(c['ord']):02d}",
                "kind": kind,
                "question": c["question"],
                "reference_answer": c.get("reference_answer"),
                "expected_document_titles": exp_titles,
                "tags": tags,
            }
        )

    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    answerable = sum(1 for r in rows if r["kind"] == "answerable")
    print(f"wrote {len(rows)} -> {OUT} (answerable={answerable} ood={len(rows) - answerable})")


if __name__ == "__main__":
    main()
