"""Expand live eval baseline (≥120) from eval_baseline_live.jsonl.

Outputs eval_baseline_expanded.jsonl keyed by document *titles* (resolved at seed time).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tests/fixtures/eval_baseline_live.jsonl"
OUT = ROOT / "tests/fixtures/eval_baseline_expanded.jsonl"

# Hand-written paraphrases: baseline id -> list of (lang_tag, question)
PARAPHRASES: dict[str, list[tuple[str, str]]] = {
    "baseline-01": [
        ("zh", "ESXI 新建虚拟机时视频内存一般设多少比较合适？"),
        ("en", "What video memory size is recommended when creating a VM on ESXI?"),
        ("vi", "Khi tạo máy ảo trên ESXI, nên đặt bộ nhớ video bao nhiêu?"),
    ],
    "baseline-02": [
        ("zh", "装 ESXI 虚拟机之前 ISO 镜像怎么传到数据存储？"),
        ("en", "How do I upload the OS ISO to the datastore before installing an ESXI VM?"),
        ("vi", "Trước khi cài VM ESXI, làm sao tải ISO lên datastore?"),
    ],
    "baseline-03": [
        ("zh", "如何判断是不是仿冒邮件？正规公司邮箱域名有哪些？"),
        ("en", "How to spot phishing email and which domains are official company mail?"),
        ("vi", "Làm sao nhận biết email giả mạo và tên miền thư công ty chính thức là gì?"),
    ],
    "baseline-04": [
        ("zh", "仿冒邮件可能造成什么损失？"),
        ("en", "What harms can spoofed phishing emails cause?"),
        ("vi", "Email giả mạo có thể gây những thiệt hại nào?"),
    ],
    "baseline-05": [
        ("zh", "防火墙主要能做什么？"),
        ("en", "What are the main functions of a firewall?"),
        ("vi", "Tường lửa có những chức năng chính nào?"),
    ],
    "baseline-06": [
        ("zh", "哪些攻击场景防火墙防不住？"),
        ("en", "What attacks can a firewall not prevent?"),
        ("vi", "Những tình huống nào tường lửa không phòng được?"),
    ],
    "baseline-07": [
        ("zh", "WannaCry 通过什么端口扩散？勒索金额大概多少？"),
        ("en", "Which port did WannaCry use to spread and what ransom was demanded?"),
        ("vi", "WannaCry lây qua cổng nào và tiền chuộc khoảng bao nhiêu?"),
    ],
    "baseline-08": [
        ("zh", "公司电脑装的杀毒软件是什么？自动扫描安排在什么时候？"),
        ("en", "Which antivirus does the company use and when does auto-scan run?"),
        ("vi", "Máy công ty dùng phần mềm diệt virus nào và quét tự động lúc nào?"),
    ],
    "baseline-09": [
        ("zh", "为什么下载软件时不要点「高速下载」？"),
        ("en", "Why should I avoid the high-speed download button when downloading software?"),
        ("vi", "Vì sao khi tải phần mềm không nên bấm tải tốc độ cao?"),
    ],
    "baseline-10": [
        ("zh", "机柜巡检是周几？机房空调温度控制范围？"),
        ("en", "Which weekdays are cabinet inspections and what room temperature is required?"),
        ("vi", "Ngày nào trong tuần phải kiểm tra tủ máy và nhiệt độ phòng máy là bao nhiêu?"),
    ],
    "baseline-11": [
        ("zh", "自动锁屏要设几分钟？快速锁屏快捷键？"),
        ("en", "What auto lock timeout and shortcut should be used?"),
        ("vi", "Thời gian khóa màn hình tự động bao lâu và phím tắt là gì?"),
    ],
    "baseline-12": [
        ("zh", "人员离职后 IT 要回收哪些账号权限？"),
        ("en", "Which accounts and permissions must IT revoke after an employee leaves?"),
        ("vi", "Nhân viên nghỉ việc thì IT cần thu hồi những quyền nào?"),
    ],
    "baseline-13": [
        ("zh", "邮件 553 authentication is required 怎么排查？"),
        ("en", "How to fix SMTP error 553 authentication is required?"),
        ("vi", "Lỗi thư 553 authentication is required xử lý thế nào?"),
    ],
    "baseline-14": [
        ("zh", "552 Message size exceeds fixed limit 表示什么？"),
        ("en", "What does 552 Message size exceeds fixed limit mean?"),
        ("vi", "Thông báo 552 Message size exceeds fixed limit nghĩa là gì?"),
    ],
    "baseline-15": [
        ("zh", "对方邮箱满了退信常见提示有哪些？如何处理？"),
        ("en", "What bounce messages appear when the recipient mailbox is full and what to do?"),
        ("vi", "Hộp thư đối phương đầy thì báo lỗi gì và phải làm sao?"),
    ],
    "baseline-16": [
        ("zh", "远程看服务器故障信息的步骤是什么？"),
        ("en", "How do I remotely view server fault information?"),
        ("vi", "Làm thế nào để xem thông tin lỗi máy chủ từ xa?"),
    ],
    "baseline-17": [
        ("zh", "思科 ACL 如何禁止某 VLAN 访问 192.168.0.10 又放行其他地址？"),
        ("en", "How to configure Cisco ACL to deny one VLAN to 192.168.0.10 but allow others?"),
        ("vi", "Cấu hình ACL Cisco để cấm VLAN truy cập 192.168.0.10 nhưng cho phép địa chỉ khác?"),
    ],
    "baseline-18": [
        ("zh", "申洲邮箱网盘有哪些诊断 IP？"),
        ("en", "What are the Shenzhou mailbox diagnostic IP addresses?"),
        ("vi", "Các địa chỉ IP chẩn đoán hộp thư Thân Châu là gì?"),
    ],
    "baseline-19": [
        ("zh", "总部财务科宝利通视频会议设备 IP 是多少？"),
        ("en", "What is the Polycom video conference IP for HQ finance?"),
        ("vi", "IP thiết bị hội nghị Polycom của phòng tài chính trụ sở là bao nhiêu?"),
    ],
    "baseline-20": [
        ("zh", "国内出差住宿报销上限怎么规定？"),
        ("en", "What are the domestic travel hotel reimbursement caps?"),
        ("vi", "Mức hoàn tiền khách sạn công tác trong nước quy định thế nào?"),
    ],
    "baseline-21": [
        ("zh", "出差回来报销期限与必须附带材料？"),
        ("en", "How soon after travel must expenses be filed and which attachments are required?"),
        ("vi", "Sau công tác bao lâu phải nộp hoàn ứng và cần kèm giấy tờ gì?"),
    ],
    "baseline-22": [
        ("zh", "飞织生产纱线张力与针床温度标准？"),
        ("en", "What yarn tension and needle bed temperature are required for flyknit?"),
        ("vi", "Tiêu chuẩn lực căng sợi và nhiệt độ giường kim khi dệt flyknit?"),
    ],
    "baseline-23": [
        ("zh", "上季度营收同比如何？哪一区贡献最大？"),
        ("en", "What was last quarter revenue growth and which region contributed most?"),
        ("vi", "Doanh thu quý trước tăng bao nhiêu và khu vực nào đóng góp lớn nhất?"),
    ],
    "baseline-24": [
        ("zh", "设备考核优/良/合格/不合格分数线？"),
        ("en", "How are equipment assessment grades scored?"),
        ("vi", "Thang điểm đánh giá thiết bị (ưu/khá/đạt/không đạt) chia thế nào?"),
    ],
}

NEW_CASES: list[dict[str, object]] = [
    {
        "id": "new-room-01",
        "kind": "answerable",
        "question": "机房设备巡检每天什么时候做？发现异常找谁？",
        "reference_answer": "机房每天上午九点巡检一次，记录温湿度与 UPS 状态，发现异常立即上报 IT 运维值班人员。",
        "expected_document_titles": ["机房设备巡检制度"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-room-02",
        "kind": "answerable",
        "question": "机房巡检要记录哪些状态？",
        "reference_answer": "记录温湿度与 UPS 状态。",
        "expected_document_titles": ["机房设备巡检制度"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-room-en",
        "kind": "answerable",
        "question": "When is the daily data-center equipment inspection and whom to escalate?",
        "reference_answer": "机房每天上午九点巡检一次，记录温湿度与 UPS 状态，发现异常立即上报 IT 运维值班人员。",
        "expected_document_titles": ["机房设备巡检制度"],
        "tags": ["expanded", "new", "ops", "en"],
    },
    {
        "id": "new-remote-01",
        "kind": "answerable",
        "question": "远程遥控 knit 网络服务器用什么工具连哪台地址？",
        "reference_answer": "用 MSTSC 远程连接 10.10.131.189，打开 Essentials，再按服务器清单查找序列号。",
        "expected_document_titles": ["如何远程遥控knit网络的服务器"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-remote-02",
        "kind": "answerable",
        "question": "How do I remote-control knit network servers?",
        "reference_answer": "用 MSTSC 远程连接 10.10.131.189，打开 Essentials，再按服务器清单查找序列号。",
        "expected_document_titles": ["如何远程遥控knit网络的服务器"],
        "tags": ["expanded", "new", "ops", "en"],
    },
    {
        "id": "new-ingest-01",
        "kind": "answerable",
        "question": "入库指南里文档上传后会经过哪些步骤？",
        "reference_answer": "文档上传后会经过解析、切分、向量化与索引等步骤，最终支持混合检索与智能问答。",
        "expected_document_titles": ["入库指南"],
        "tags": ["expanded", "new", "platform"],
    },
    {
        "id": "new-ingest-02",
        "kind": "answerable",
        "question": "检索结果如何按权限过滤？",
        "reference_answer": "所有检索结果都会按照用户的部门、用户组与角色进行权限过滤。",
        "expected_document_titles": ["入库指南"],
        "tags": ["expanded", "new", "platform"],
    },
    {
        "id": "new-deploy-01",
        "kind": "answerable",
        "question": "部署指南里 PDF_PARSER 默认值是什么？",
        "reference_answer": "PDF_PARSER 默认值为 auto，表示 PDF 解析后端自动选择。",
        "expected_document_titles": ["部署指南"],
        "tags": ["expanded", "new", "platform"],
    },
    {
        "id": "new-deploy-02",
        "kind": "answerable",
        "question": "OCR_ENABLED 默认是否开启？",
        "reference_answer": "OCR_ENABLED 默认为 true，用于扫描件 OCR。",
        "expected_document_titles": ["部署指南"],
        "tags": ["expanded", "new", "platform"],
    },
    {
        "id": "new-stock-01",
        "kind": "answerable",
        "question": "物料库存表里 M-0001 飞织鞋面材料1 的单价和库存是多少？",
        "reference_answer": "单价 13.50 元，库存 3。",
        "expected_document_titles": ["物料库存"],
        "tags": ["expanded", "new", "mes"],
    },
    {
        "id": "new-stock-02",
        "kind": "answerable",
        "question": "物料库存汇总里鞋面类别数量是多少？",
        "reference_answer": "鞋面类别数量为 42。",
        "expected_document_titles": ["物料库存"],
        "tags": ["expanded", "new", "mes"],
    },
    {
        "id": "new-cam-01",
        "kind": "answerable",
        "question": "特种面料厂监控有哪些示例 IP？",
        "reference_answer": "例如 6.131.1.241～6.131.1.249 以及 6.131.2.241～6.131.2.249 等监控地址；另有 6.131.1.225 标注为海关录像机。",
        "expected_document_titles": ["面料厂最新监控ip"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-cam-02",
        "kind": "answerable",
        "question": "海关录像机对应的监控 IP 是多少？",
        "reference_answer": "6.131.1.225（海关录像机）。",
        "expected_document_titles": ["面料厂最新监控ip"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-handbook-01",
        "kind": "answerable",
        "question": "员工手册总则里平台检索如何保证安全？",
        "reference_answer": "所有检索结果都会按照用户的部门、用户组与角色进行权限过滤。",
        "expected_document_titles": ["员工手册"],
        "tags": ["expanded", "new", "hr"],
    },
    {
        "id": "new-handbook-02",
        "kind": "answerable",
        "question": "员工手册物料清单中 M-0002 的规格是什么？",
        "reference_answer": "飞织鞋面材料2，规格 102g/m²。",
        "expected_document_titles": ["员工手册"],
        "tags": ["expanded", "new", "hr"],
    },
    {
        "id": "new-esxi-extra",
        "kind": "answerable",
        "question": "ESXI 虚拟机显存设太小会出现什么现象？",
        "reference_answer": "设置过小会导致虚拟机分辨率较小（如 800*600）。",
        "expected_document_titles": ["ESXI创建安装虚拟机步骤"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-mail-extra",
        "kind": "answerable",
        "question": "SMTP 需要认证时要在哪里勾选？",
        "reference_answer": "在个人信息中填写正确邮箱地址，并勾选“SMTP服务器需要认证”。",
        "expected_document_titles": ["发送邮件常见出错代码及简单解决方法"],
        "tags": ["expanded", "new", "ops"],
    },
    {
        "id": "new-assess-extra",
        "kind": "answerable",
        "question": "设备考核总分多少？85 分算什么等级？",
        "reference_answer": "总分 100 分；85-89.9 为合格，85 分以下不合格。",
        "expected_document_titles": ["设备考核(暂行)3"],
        "tags": ["expanded", "new", "ops"],
    },
]

EXTRA_OOD: list[str] = [
    "公司班车几点发车？",
    "园区停车位怎么申请？",
    "员工体检多久一次？",
    "公积金贷款额度怎么算？",
    "产假工资怎么发？",
    "公司健身房开放时间？",
    "宿舍怎么申请入住？",
    "团建费用报销额度？",
    "外包人员工牌怎么办理？",
    "内部论坛账号怎么注册？",
    "How many paid sick-leave days do we get?",
    "Where do I apply for a company laptop?",
    "Công ty có hỗ trợ tiền nhà ở không?",
    "Lịch nghỉ Tết Nguyên đán năm nay thế nào?",
    "公司股票期权行权价格是多少？",
    "访客 Wi-Fi 密码是什么？",
]


def _load(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def main() -> None:
    base = _load(SRC)
    by_id = {str(r["id"]): r for r in base}
    out: list[dict[str, object]] = []
    seen_q: set[str] = set()

    def add(row: dict[str, object]) -> None:
        q = str(row["question"]).strip()
        if not q or q in seen_q:
            return
        seen_q.add(q)
        out.append(row)

    for row in base:
        add(row)

    for bid, variants in PARAPHRASES.items():
        src = by_id[bid]
        for i, (lang, question) in enumerate(variants):
            add(
                {
                    "id": f"{bid}-p{i:02d}-{lang}",
                    "kind": src["kind"],
                    "question": question,
                    "reference_answer": src.get("reference_answer"),
                    "expected_document_titles": list(src.get("expected_document_titles") or []),
                    "tags": ["expanded", "paraphrase", lang, *list(src.get("tags") or [])],
                }
            )

    for row in NEW_CASES:
        add(row)

    for i, q in enumerate(EXTRA_OOD, start=1):
        add(
            {
                "id": f"ood-extra-{i:02d}",
                "kind": "ood",
                "question": q,
                "reference_answer": "知识库中没有相关内容，应拒答。",
                "expected_document_titles": [],
                "tags": ["expanded", "negative", "ood"],
            }
        )

    if len(out) < 120:
        raise SystemExit(f"only {len(out)} cases; need ≥120")

    OUT.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out),
        encoding="utf-8",
    )
    answerable = sum(1 for r in out if r["kind"] == "answerable")
    print(
        f"wrote {len(out)} -> {OUT} "
        f"(answerable={answerable} ood={len(out) - answerable})"
    )


if __name__ == "__main__":
    main()
