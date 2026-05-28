# AGENTS.md

> 项目级导航。任何在本仓库工作的 agent / 开发者**先读本文档**，定位自己的任务属于哪个子系统、应该深入哪份具体文档。

## 项目是什么

**job-analysis** 是一个本地工具，抓取职位 URL → 整合企查查公司数据 → 跑 LLM 多 agent 分析 → 在前端可视化报告。

完整功能介绍见根目录 [`README.md`](README.md)。

## 项目结构

```
project-root/
├── README.md                       ← 用户/开发者入口，环境搭建、CLI 用法
├── AGENTS.md                       ← 你正在读
│
├── main.py                         ← 后端 CLI 总入口（抓取 + 公司整合 + LLM 分析）
├── scraper/                        ← CDP Chrome 抓取与页面清洗
│   ├── cdp_scraper.py
│   ├── job_scraper.py
│   └── cleaner.py
├── external_data/                  ← 企查查 MCP 数据整合
│   ├── enrich.py
│   ├── company_resolver.py
│   ├── qcc_client.py
│   ├── mcp_client.py
│   ├── company_cache.py
│   └── industry_fetcher.py
├── analyzers/                      ← LLM 子 agent
│   ├── _shared.py
│   ├── job_value_agent.py          ← 职位综合价值（含 4 维子分）
│   ├── company_risk_agent.py       ← 公司健康度
│   ├── industry_outlook_agent.py   ← 行业前景
│   └── final_evaluation_agent.py   ← 综合评估 + 申请建议
├── llm.py                          ← 多 provider LLM 封装
│
├── frontend/                       ← Angular 19 + Material 前端
│   └── src/app/                    ── core / shared / layout / features 四层结构
│
├── candidate_profile.example.json  ← 候选人画像模板
├── candidate_profile.json          ← 用户实际画像（gitignored）
│
├── requirements.txt
├── pyproject.toml
│
├── data/                           ← 每次运行产物（gitignored）
├── .chrome-debug-profile/          ← 持久化 Chrome 登录态（gitignored）
│
├── index.html                      ← 前端高保真原型（设计源稿）
│
└── doc/
    ├── frontend.md                 ← 前端架构 / 模块设计总结
    └── fit.md                      ← 前后端对接契约（HTTP / SSE / 数据 schema）
```

## 子系统与文档索引

| 我要做什么 | 看哪份文档 | 主要相关代码 |
| --- | --- | --- |
| 跑通现有 CLI / 配环境 / 了解整体流程 | [`README.md`](README.md) | `main.py` |
| **写 FastAPI 后端 / 对接前端** | [`doc/fit.md`](doc/fit.md) | （新建）`web/app.py` |
| **改前端 UI / 加新页面 / 加新组件** | [`doc/frontend.md`](doc/frontend.md) | `frontend/src/app/` |
| 改抓取逻辑 / CDP 行为 | `README.md` 「为什么用 CDP」段 | `scraper/cdp_scraper.py` 等 |
| 改 LLM prompt / 加新 analyzer | `analyzers/*.py` 自身注释 | `analyzers/*_agent.py` |
| 改 QCC 数据整合 / 公司锚定 | （暂无独立文档） | `external_data/enrich.py` 等 |
| 候选人画像字段语义 | `candidate_profile.example.json` 内的注释 | `main.py::load_candidate_profile` |

## 跨子系统的关键契约

1. **数据流向：**
   ```
   URL → main.py → data/<slug>/ 产物（job_cleaned.json / company.json / analysis.json / summary.json）
                                      ↓
                            FastAPI 读取 + 适配为前端 schema
                                      ↓
                              Angular 前端展示
   ```

2. **前后端字段命名硬约束：**
   - 接口 JSON 中**禁止任何中文 object key**，一律英文 camelCase
   - 中文只允许作为字符串「值」（用户可见 label / 文案）出现
   - 完整 schema 见 [`doc/fit.md`](doc/fit.md)

3. **后端 LLM 输出 → 前端类型的 adapter** 是关键收口点。`analyzers/*.py` 的 `EXPECTED_KEYS` 还在 prompt 调整中，所以 FastAPI 一定要写 adapter 函数，**不要让 analyzer 原始输出直接漏到 HTTP 层**。详见 [`doc/fit.md`](doc/fit.md) 第 4 节。

4. **前端与后端的解耦点：** `frontend/src/app/core/services/api.service.ts`。后端 schema 变化时，所有适配在这一个文件里完成，组件代码不动。

5. **抓取层（CDP）必须本地运行：** 依赖 `127.0.0.1:9222` + `.chrome-debug-profile/`，不能部署到远程服务器。后端 FastAPI 也只在本机起。

## 当前状态

- ✅ Python CLI 抓取 / QCC 整合 / 4 个 analyzer 已实装（主流程暂时屏蔽 LLM，详见 README）
- ✅ Angular 前端骨架完成，所有页面跑得起来（吃 mock 数据）
- ⏳ FastAPI 后端尚未实装 —— 这是下一步的主任务，参照 [`doc/fit.md`](doc/fit.md)

## 行为约定

- 在编辑代码前，先看子系统对应文档；不要凭空猜测字段名 / 路径
- 修改跨子系统接口时（如改 `JobAnalysis` 类型、改 `analyzer.EXPECTED_KEYS`），同步更新对应文档
- 不在 README / AGENTS.md 里堆细节 —— 细节归属于各子系统文档
- 添加新子系统时，在本文档「项目结构」+「子系统与文档索引」两处补登记
