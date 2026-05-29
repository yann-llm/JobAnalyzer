# job-analysis

![job-analysis cover](https://img.ylaizxx.cn/2feaa32d-bcc4-4747-86dd-f2c498f064b3.avif)

抓取一个职位 URL 的页面内容，清洗后整合企查查公司数据（若已配置），运行多 LLM 子 agent 分析，并通过 FastAPI + Angular 前端展示职位报告。

抓取走 **Chrome 远程调试协议（CDP）+ 持久化 profile**：脚本自动启动一个长驻 Chrome 进程，登录一次后 cookies 永久保存在本地，后续运行无感知。

项目包含两部分：
- **Python 后端**（`main.py` + `web/` + `scraper/` + `external_data/` + `analyzers/`）：CLI 抓取 + QCC 整合 + LLM 分析 + FastAPI API / SSE
- **Angular 前端**（`frontend/`）：可视化职位分析报告、提交 URL、SSE 进度展示、历史列表、公司弹窗与导出

## 为什么用 CDP（而不是 Playwright / opencli）

| 维度 | CDP + `--remote-debugging-port` | Playwright Chromium | opencli `chrome.debugger.attach` |
| --- | --- | --- | --- |
| Chrome 顶部 debug 横幅 | **无** | 无（但有 `navigator.webdriver=true`） | **有黄色 "OpenCLI started debugging…"** |
| Zhipin `debugger;` 陷阱命中 | 否 | 看具体页面 | 是 → 页面跳 `about:blank` |
| 登录状态 | 持久化在 profile 目录里 | 持久化 | 看 opencli profile |
| tab 生命周期 | 永远不被脚本关闭 | 受脚本控制 | 受 opencli lease 控制，可能误关 |

## 项目结构

```
job-analysis/
├── start_job_analysis.bat          ← Windows 双击启动入口
├── start_job_analysis.ps1          ← 一键启动实际逻辑（后端 + 前端 + 浏览器）
├── web/
│   ├── app.py                      ← FastAPI API / SSE 入口
│   └── adapters.py                 ← analysis.json → 前端 schema 适配层
├── pipeline/                       ← 主流程拆分：职位抓取、公司页抓取、公司数据、行业查询、LLM
├── llm.py                          ← 多 provider LLM 封装
├── .env.example
├── candidate_profile.example.json  ← 候选人画像模板
├── main.py                         ← 总入口
├── scraper/
│   ├── cdp_scraper.py              ← CDP 核心：启动 Chrome、找 tab、Runtime.evaluate
│   ├── job_scraper.py              ← 对外 API：fetch_job_page
│   └── cleaner.py                  ← 文本清洗 + 字段抽取
├── external_data/
│   ├── enrich.py                   ← 清洗后、agent 前的企查查数据整合
│   ├── qcc_client.py               ← qcc-company / qcc-risk MCP 调用封装
│   └── uscc_lookup.py              ← 页面缺失 USCC 时，用 LLM + Tavily tool 查询经营主体与信用代码
├── analyzers/                      ← LLM 分析模块
│   ├── _shared.py                  ← 公共上下文构造（含候选人画像注入）
│   ├── job_value_agent.py          ← 子 agent 1：职位综合价值（职责/要求/薪酬/强度多维评分）
│   ├── company_risk_agent.py       ← 子 agent 2：公司主体健康度与风险（基于企查查）
│   ├── industry_outlook_agent.py   ← 子 agent 3：行业与赛道前景（基于模型常识，带 provenance）
│   └── final_evaluation_agent.py   ← 汇总 agent
├── frontend/                       ← Angular 19 + Material 前端（独立子项目）
│   ├── src/app/
│   │   ├── core/                   ← 数据模型 / mock 数据 / ApiService（mock ↔ 真实切换）
│   │   ├── shared/                 ← 雷达图、评分工具等可复用组件
│   │   ├── layout/                 ← 应用外壳 + 侧边历史抽屉
│   │   └── features/
│   │       ├── dashboard/          ← 主页：hero 搜索 + 评分总览 + 6 维 tab + 公司 modal
│   │       ├── submit-progress/    ← SSE 进度页
│   │       └── candidate-profile/  ← 候选人画像编辑
│   └── src/environments/           ← useMock 开关
├── .chrome-debug-profile/          ← 自动创建，持久化登录态（已 gitignore）
└── data/                           ← 每次运行产物（已 gitignore）
```

## 环境

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt

copy .env.example .env
# 编辑 .env，按 .env.example 填入 MODEL_NAME、OPENAI_API_KEY / ANTHROPIC_API_KEY 等配置
```

若需要页面缺失 USCC 时的网络兜底查询，还需要配置 `TAVILY_API_KEY`。当前 USCC 兜底查询通过 **LLM function/tool calling + Tavily** 实现，要求使用 OpenAI-compatible provider；页面已直接抓到 USCC 的场景不依赖该兜底。

前端依赖首次安装：

```bash
cd frontend
npm install
```

无需 `playwright install`，也无需安装 opencli / 浏览器扩展，只要本机已经装了 Google Chrome 或 Microsoft Edge 即可。如果可执行文件不在标准路径，可以设置环境变量 `CHROME_PATH=/path/to/chrome.exe`。

### 候选人画像（可选）

```bash
cp candidate_profile.example.json candidate_profile.json
# 编辑这个文件，填入你的工作年限、技能、城市、薪资底线、可接受加班强度等
```

后端分析流程会读取 `candidate_profile.json`（存在且合法时）并注入 LLM 上下文；该文件已加入 `.gitignore`，不会被提交到 git。前端候选人画像页面目前仍是占位编辑界面，保存逻辑后续再接。

### 当前数据来源说明

| 数据块 | 数据来源 | 说明 |
| --- | --- | --- |
| `raw_page.html` | CDP 页面抓取 | 页面 HTML，便于排查抓取质量 |
| `job_cleaned.json` | 页面原文 | 职位名、薪资、地点、经验、学历、描述、工商摘要等核心字段 |
| `company.json` / `_company_cache` | 页面 / LLM+Tavily / 企查查 MCP + 行业 Tavily 查询 | 企业锚定、工商信息、风险信息与行业数据缓存 |
| `analysis.json` | LLM analyzers | 职位价值、公司风险、行业前景、最终评估的结构化结果 |

后续 LLM 分析要求先取得公司信息：流程会先从职位页 / 公司详情页抽取有效 18 位 USCC；如果页面没有 USCC，会把公司名交给大模型，并将 Tavily 作为工具提供给大模型，由模型查询经营主体全称与 USCC。取得 USCC 后才进入 QCC 查询公司工商 / 风险 / 经营数据；仍无法取得 USCC 时直接报“获取公司信息失败”，不会进入 QCC 数据整合。

LLM 分析阶段中，`job_value`（职位综合价值）、`company_risk`（公司风险）、`industry_outlook`（行业前景）三个子模块并行调用；`final_evaluation` 依赖前三个结果，最后串行执行。

## 使用流程

### Windows 一键启动（推荐）

双击项目根目录的：

```text
start_job_analysis.bat
```

脚本会：

1. 检查 `python` 和 `npm` 是否可用。
2. 检查项目虚拟环境 `.venv`；不存在时自动执行 `python -m venv .venv`。
3. 检查 Python 运行依赖；缺失时使用 `.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装到虚拟环境。
4. 检查前端依赖；缺少 `frontend/node_modules/.bin/ng.cmd` 时自动执行 `npm install`。
5. 若 `.env` 不存在，提醒用户复制 `.env.example` 并填写大模型 key（不会阻止启动）。
6. 若 `127.0.0.1:8000` 没有服务，使用 `.venv` 里的 Python 启动 FastAPI 后端（`uvicorn --reload`，Python 代码变更会自动重载）。
7. 若 `127.0.0.1:4200` 没有服务，启动 Angular 前端。
8. 打开浏览器访问 `http://127.0.0.1:4200`。

启动后会留下两个服务窗口：

| 窗口 | 用途 | 关闭后果 |
| --- | --- | --- |
| JobScope API | FastAPI 后端 `:8000`（自动 reload） | 前端无法请求接口 |
| JobScope Frontend | Angular dev server `:4200` | 页面无法访问 |

重复点击脚本时，如果端口已有服务，会直接复用，不会再启动第二个前端服务。

### 前端分析流程

1. 打开 `http://127.0.0.1:4200`。
2. 粘贴 BOSS 直聘职位 URL。
3. 点击「开始分析」。
4. 前端提交 `POST /api/analyze`，随后通过 SSE 订阅 `/api/analyze/{taskId}/stream`。
5. 完成后自动跳转 `/results/:slug`，历史列表自动刷新。
6. 点击「重新分析」会调用 `POST /api/results/{id}/reanalyze`，重新跑抓取和 LLM 分析；公司 / QCC 缓存未过期时会继续复用。

### CLI 首次运行

```bash
python main.py "https://www.zhipin.com/job_detail/xxx.html"
```

脚本会：

1. 探测 `127.0.0.1:9222`，不在 → 用 `--remote-debugging-port=9222 --user-data-dir=.chrome-debug-profile/` 启动一个**可见的** Chrome 窗口，并直接打开目标 URL。
2. 检测到页面被跳转到登录页 → 在终端提示「请在 Chrome 窗口完成登录」。
3. 你登录完成后，脚本自动检测 URL 不再含 `/login`/`/web/user` 等关键字，再用 `Page.navigate` 把 tab 导回目标 URL。
4. 抓取 title / text / html → 清洗文本 → 获取统一社会信用代码（页面抽取；失败时 LLM+Tavily tool 兜底）→ 调用企查查整合公司工商 / 风险数据（缓存未过期则复用）→ 并行运行前三个 LLM 子分析 → 运行最终评估 → 保存到 `data/<host_path>/`。

登录态保存在 `.chrome-debug-profile/`，**仅此一次**。

### 后续运行

```bash
python main.py "https://www.zhipin.com/job_detail/another.html"
```

- 如果上次的 Chrome 窗口还开着（推荐保留）→ 探测到 9222 → 直接复用，全程无任何用户操作。
- 如果你关了 Chrome → 脚本自动重新启动 Chrome（同一个 profile，cookies 自动恢复）→ 直接打开目标 URL → 抓取。

### CLI 参数

| 参数 | 说明 |
| --- | --- |
| `--profile-dir PATH` | 覆盖默认 profile 目录（默认 `.chrome-debug-profile/`） |
| `--port N` | 覆盖 CDP 端口（默认 9222） |
| `--no-existing-tab` | 不复用已打开的 tab，强制新开 |
| `--screenshot` | 保存整页截图 |
| `--login-wait SEC` | 等待用户首次登录的最大秒数（默认 600） |
| `--no-analysis` | 只抓取和整合公司数据，不运行 LLM 分析 |

## 输出

每个职位 URL 会稳定落在 `data/<host_path>/` 下；同一个页面地址会复用同一个目录，便于后续作为缓存使用。

| 文件 | 含义 |
| --- | --- |
| `raw_page.html` | 通过 CDP 拿到的页面 HTML（最多 400k 字符） |
| `job_cleaned.json` | 前端 / analyzer 使用的职位核心字段 |
| `company.json` | 公司缓存引用（USCC、公司名、缓存路径） |
| `analysis.json` | 4 个 analyzer + final evaluation 的完整 LLM 结果 |
| `screenshot/job_*.png` | 全页截图（仅 `--screenshot` 时生成） |
| `data/_company_cache/<USCC>.json` | QCC / 行业数据缓存，按 TTL 复用 |

## 前端（Angular）

`frontend/` 目录是一个独立的 Angular 19 + Material 应用，把 `data/` 下的分析产物渲染成可视化报告，并提供 URL 提交、SSE 进度展示、候选人画像编辑等交互入口。

前端当前默认连接真实 FastAPI API（`useMock: false`）。如需离线开发 UI，可临时切回 mock 模式。

### 环境

只要装好 Node.js 18+（推荐 20 或 24）即可，不需要全局安装 `@angular/cli`，命令统一走 `npx`。

```bash
cd frontend
npm install        # 首次安装依赖
npm start -- --host 127.0.0.1 --port 4200
# → http://127.0.0.1:4200
```

### 路由

| 路径 | 用途 |
| --- | --- |
| `/` | 主页：Hero 搜索条 + 历史中第一条职位的完整分析报告 |
| `/results/:id` | 指定职位的分析报告（综合评分 + 6 维详情 + 雷达图） |
| `/jobs/:taskId` | 任务进度页：SSE 推送抓取、公司详情页、QCC、LLM 子模块与完成状态 |
| `/profile` | 候选人画像编辑（基本信息 / 技能 / 职业目标 / 约束 / 偏好） |

### 数据切换

`frontend/src/environments/environment.ts` 控制 mock 与真实 API：

```ts
export const environment = {
  useMock: false,                     // true 走 mock；false 走真实 API
  apiBase: 'http://127.0.0.1:8000',  // FastAPI 后端地址
};
```

- mock 数据来源：`frontend/src/app/core/mock/jobs.mock.ts`（与设计稿 `index.html` 的 `JOBS` / `COMPANIES` 完全对齐，3 个职位 + 3 家公司）
- 真实数据来源：FastAPI 读取 `data/<slug>/analysis.json`、`job_cleaned.json`、`company.json`，经 `web/adapters.py` 转成前端 `JobAnalysis` / `Company` 类型

### 视觉风格

紫色品牌主题（`#7132f5`）+ 自定义 CSS 变量，所有设计 token 集中在 `frontend/src/styles.scss`。Material 组件（Dialog / Expansion / FormField 等）只用功能、套上同一套主题色，保持与原型 `index.html` 视觉一致。

### 构建

```bash
cd frontend
npx ng build                            # 生产构建，产物在 frontend/dist/
npx ng build --configuration development  # 开发构建（带 source map）
```

## 常见问题

**Q: 我已经在自己日常的 Chrome 里登录了 BOSS 直聘，脚本能复用吗？**
不能直接复用 —— CDP 走的是独立 profile（`.chrome-debug-profile/`），跟你日常 Chrome 是两个隔离的实例。在 CDP profile 里登录一次即可，之后 cookies 一直在那个目录里。

**Q: Chrome 窗口能最小化或者藏到后台吗？**
可以最小化，但不要关闭。每次脚本运行若发现 9222 没监听，就会重启 Chrome —— 也能用，只是多花几秒启动时间。

**Q: 想要 headless 模式怎么办？**
当前流程默认可见窗口，方便首次登录。如果你的 cookies 已经稳定，可以在 `cdp_scraper.launch_chrome_with_cdp` 的 args 里加 `"--headless=new"`。

**Q: 前端运行报 `npm error could not determine executable to run`？**
通常是在错误的目录跑 `npx ng ...`。`@angular/cli` 只装在 `frontend/node_modules/` 下，必须先 `cd frontend` 再跑命令。如果 `frontend/node_modules/` 为空，先 `npm install`。

**Q: 前端报错或样式异常，但 mock 数据没改？**
检查 `frontend/src/environments/environment.ts` 的 `useMock` 和 `apiBase`。当前默认 `useMock: false`，需要先启动 FastAPI 后端；离线开发 UI 时可临时改成 `useMock: true`。

**Q: 双击启动脚本后出现两个前端服务？**
新版 `start_job_analysis.ps1` 会先检测 `127.0.0.1:4200`，如果已有前端服务就复用。若旧窗口还开着，关闭多余的 `JobScope Frontend` 命令行窗口即可。
