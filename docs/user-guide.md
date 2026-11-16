# 使用说明（入口）

> **产品内权威手册**：登录后顶栏 **帮助 → 使用说明**（路由 `/guide`）。  
> 章节与步骤按你的角色权限自动过滤；中英文与界面语言一致。  
> 本文只做角色导读与仓库文档索引，避免与应用内文案双源漂移。

---

## 1. 谁该看哪里

| 角色 | 先看应用内章节 | 日常入口 |
| --- | --- | --- |
| 普通员工 | 快速开始 → 知识库问答专家 → 搜索 → 知识库 → 我的收藏 → 消息通知 | 提问、搜原文、收藏 |
| 知识运营 | 概念层 + 知识运营（缺口 / 条目关系 / 审核）+ 知识库上传与编辑 | 补知识、发布、维护 KO 图谱边 |
| 组织管理员 | 管理后台（同步、部门、用户、组、角色、审计）+ AI 管理助手 | 账号与权限 |
| 检索/概念管理员 | 概念层 + 术语表 + 结构化数据映射/同步 | 别名、编号对齐、同义词同步 |
| 平台工程 | 平台工程（索引、模型、检索含图召回、评测、开放平台）+ 分析 | 检索质量与接入 |
| 系统运维（宿主机 / Compose） | 下文「运维文档」 | 部署、备份、告警、安全开关 |

开发预置账号见仓库 [README](../README.md)（如 `alice` / `bob` / `carol`）。

---

## 2. 应用内章节目录

与 `frontend/src/guide/content/manual.zh-CN.ts` 对齐：

1. 快速开始  
2. 知识库问答专家（含「相关概念」）  
3. 知识库  
4. 搜索  
5. 我的收藏  
6. 消息通知  
7. **概念层**（术语 / 实体 / 图谱 / 本体：目的与名词）  
8. **知识运营**（缺口看板与工作台、知识条目关系、审核发布）  
9. 管理后台（含**术语表**逐步操作、**结构化数据**映射与同步）  
10. AI 管理助手  
11. 平台工程  
12. 分析  
13. FAQ  

概念层相关运维补充：[ontology.md](ontology.md)、[ops/structured-connectors.md](ops/structured-connectors.md)。

页面内可「去体验」跳转对应功能，或「播放引导」重看 Tour。

---

## 3. 运维文档（UI 外）

| 主题 | 文档 |
| --- | --- |
| 生产 Compose 部署 | [ops/deployment.md](ops/deployment.md) |
| 单机复用宿主机 PG/Redis + HTTPS | [ops/deployment-server.md](ops/deployment-server.md) |
| 备份与恢复 | [ops/backup-restore.md](ops/backup-restore.md) |
| 备份演练纪要（样例） | [testing/backup-drill-20261114.md](testing/backup-drill-20261114.md) |
| 告警冒烟 | [ops/alerting-smoke.md](ops/alerting-smoke.md) |
| 暴露面检查 | [ops/exposure-checklist.md](ops/exposure-checklist.md) |
| PII / ClamAV 开关 | [ops/pii-clamav.md](ops/pii-clamav.md) |
| 索引重建 | [ops/reindex.md](ops/reindex.md) |
| Embedding 迁移 | [ops/embedding-migration.md](ops/embedding-migration.md) |
| 组织同步 | [ops/directory-sync.md](ops/directory-sync.md) |
| 结构化连接器 | [ops/structured-connectors.md](ops/structured-connectors.md) |
| 企微/钉钉群机器人 | [ops/group-bots.md](ops/group-bots.md) |
| 开放平台（外部 Agent / MCP） | [open-platform.md](open-platform.md) |
| 单机 HA 分阶段评估 | [adr/0003-single-node-ha-stages.md](adr/0003-single-node-ha-stages.md) |
| 系统能力总览（汇报口径） | [system-overview.md](system-overview.md) |

---

## 4. 改手册时注意

- 改操作步骤：只改 `frontend/src/guide/content/manual.zh-CN.ts`，并同步 `manual.en.ts`（结构必须一致，见 `guide/__tests__/content.spec.ts`）。  
- 越语界面暂回退英文手册。  
- 勿在本文复制长步骤正文。
