"""Expand offline retrieval_gold fixtures to >=100 cases (rankings included)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests/fixtures/retrieval_gold.jsonl"
RANK = ROOT / "tests/fixtures/retrieval_gold_rankings.json"

DOMAINS = [
    ("leave", "doc-leave-policy", "年假", "PTO", "nghi phep"),
    ("expense", "doc-expense-policy", "报销", "expense", "hoan ung"),
    ("onboard", "doc-onboarding", "入职", "onboarding", "nhan su moi"),
    ("vpn", "doc-vpn-guide", "VPN", "VPN dial", "VPN"),
    ("mail", "doc-mail-errors", "邮件出错", "mailbox full", "email loi"),
    ("fw", "doc-firewall", "防火墙", "firewall", "tuong lua"),
    ("backup", "doc-backup", "备份", "backup restore", "sao luu"),
    ("device", "doc-device-pm", "设备保养", "preventive maintenance", "bao duong"),
    ("yarn", "doc-yarn-defect", "断纱", "yarn break", "dut soi"),
    ("acl", "doc-acl-policy", "访问控制", "ACL policy", "kiem soat truy cap"),
]

ZH = [
    "{kw}相关规定是什么",
    "如何处理{kw}问题",
    "{kw}流程怎么走",
    "{kw}注意事项有哪些",
    "遇到{kw}应该找谁",
    "{kw}常见错误怎么排查",
    "{kw}标准是什么",
    "关于{kw}的制度条款",
    "{kw}需要哪些材料",
    "{kw}时效要求是多久",
]
EN = [
    "what is the policy for {kw}",
    "how to handle {kw}",
    "{kw} process steps",
    "{kw} checklist",
    "who owns {kw}",
    "troubleshoot {kw}",
    "{kw} standard",
    "rules about {kw}",
    "documents needed for {kw}",
    "{kw} SLA",
]
VI = [
    "quy dinh ve {kw}",
    "xu ly {kw} nhu the nao",
    "quy trinh {kw}",
    "luu y {kw}",
    "{kw} thuoc bo phan nao",
    "khac phuc {kw}",
    "tieu chuan {kw}",
    "chinh sach {kw}",
    "ho so can cho {kw}",
    "thoi han {kw}",
]


def main() -> None:
    cases: list[dict[str, object]] = []
    rankings: dict[str, list[str]] = {}
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        cases.append(row)
    rankings.update(json.loads(RANK.read_text(encoding="utf-8")))

    docs_pool = [d[1] for d in DOMAINS]
    for dom_key, doc_id, zh, en, vi in DOMAINS:
        others = [d for d in docs_pool if d != doc_id][:4]
        for i, tmpl in enumerate(ZH):
            cid = f"zh-{dom_key}-{i:02d}"
            cases.append(
                {
                    "id": cid,
                    "lang": "zh",
                    "query": tmpl.format(kw=zh),
                    "expected_document_ids": [doc_id],
                    "min_recall_at_5": 1.0,
                    "min_mrr": 0.5,
                    "tags": ["expanded", dom_key],
                }
            )
            rankings[cid] = [doc_id, *others]
        for i, tmpl in enumerate(EN[:4]):
            cid = f"en-{dom_key}-{i:02d}"
            cases.append(
                {
                    "id": cid,
                    "lang": "en",
                    "query": tmpl.format(kw=en),
                    "expected_document_ids": [doc_id],
                    "min_recall_at_5": 1.0,
                    "min_mrr": 0.5,
                    "tags": ["expanded", dom_key],
                }
            )
            rankings[cid] = [doc_id, *others]
        for i, tmpl in enumerate(VI[:2]):
            cid = f"vi-{dom_key}-{i:02d}"
            cases.append(
                {
                    "id": cid,
                    "lang": "vi",
                    "query": tmpl.format(kw=vi),
                    "expected_document_ids": [doc_id],
                    "min_recall_at_5": 1.0,
                    "min_mrr": 0.5,
                    "tags": ["expanded", dom_key],
                }
            )
            rankings[cid] = [doc_id, *others]

    seen: set[str] = set()
    uniq: list[dict[str, object]] = []
    for row in cases:
        cid = str(row["id"])
        if cid in seen:
            continue
        seen.add(cid)
        uniq.append(row)

    if len(uniq) < 100:
        raise SystemExit(f"expected >=100 cases, got {len(uniq)}")

    GOLD.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in uniq) + "\n",
        encoding="utf-8",
    )
    RANK.write_text(json.dumps(rankings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(uniq)} cases / {len(rankings)} rankings")


if __name__ == "__main__":
    main()
