# job-analysis

抓取一个职位 URL 的页面内容，清洗后整合企查查公司数据（若已配置），并把原始页面、清洗数据和公司信息请求结果保存到 `data/`。

> 当前处于抓取 / 公司信息请求测试模式：大模型子 agent 与最终汇总流程已在 `main.py` 中屏蔽，不会调用 LLM。

抓取走 **Chrome 远程调试协议（CDP）+ 持久化 profile**：脚本自动启动一个长驻 Chrome 进程，登录一次后 cookies 永久保存在本地，后续运行无感知。

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
├── llm.py                          ← 多 provider LLM 封装（当前主流程暂不调用）
├── llm_config.example.json
├── candidate_profile.example.json  ← 候选人画像模板（当前主流程暂不调用）
├── main.py                         ← 总入口
├── scraper/
│   ├── cdp_scraper.py              ← CDP 核心：启动 Chrome、找 tab、Runtime.evaluate
│   ├── job_scraper.py              ← 对外 API：fetch_job_page
│   └── cleaner.py                  ← 文本清洗 + 字段抽取
├── external_data/
│   ├── enrich.py                   ← 清洗后、agent 前的企查查数据整合
│   ├── company_resolver.py         ← 从页面公司名锚定唯一企业实体
│   └── qcc_client.py               ← qcc-company / qcc-risk MCP 调用封装
├── analyzers/                      ← LLM 分析模块（当前主流程暂时屏蔽）
│   ├── _shared.py                  ← 公共上下文构造（含候选人画像注入）
│   ├── basic_info_agent.py         ← 子 agent 1：基础信息
│   ├── responsibility_agent.py     ← 子 agent 2：岗位职责
│   ├── requirement_agent.py        ← 子 agent 3：候选人要求（消费候选人画像）
│   ├── compensation_agent.py       ← 子 agent 4：薪酬与福利（消费候选人画像）
│   ├── company_agent.py            ← 子 agent 5：公司与团队
│   ├── work_intensity_agent.py     ← 子 agent 6：工作强度（消费候选人画像）
│   ├── legal_risk_agent.py         ← 子 agent 7：法律合规风险
│   ├── industry_outlook_agent.py   ← 子 agent 8：行业与赛道前景（基于模型常识，带 provenance）
│   ├── company_finance_agent.py    ← 子 agent 9：公司财务健康度（基于模型常识，带 provenance）
│   └── final_evaluation_agent.py   ← 汇总 agent
├── .chrome-debug-profile/          ← 自动创建，持久化登录态（已 gitignore）
└── data/                           ← 每次运行产物（已 gitignore）
```

## 环境

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt

cp llm_config.example.json llm_config.json
# 编辑 llm_config.json 填入 provider 与 api_key
```

无需 `playwright install`，也无需安装 opencli / 浏览器扩展，只要本机已经装了 Google Chrome 或 Microsoft Edge 即可。如果可执行文件不在标准路径，可以设置环境变量 `CHROME_PATH=/path/to/chrome.exe`。

### 候选人画像（暂未启用）

```bash
cp candidate_profile.example.json candidate_profile.json
# 编辑这个文件，填入你的工作年限、技能、城市、薪资底线、可接受加班强度等
```

当前主流程只做页面抓取和公司信息请求，不会读取 `candidate_profile.json`，也不会启动子 agent。`candidate_profile.json` 已加入 `.gitignore`，不会被提交到 git。

### 当前数据来源说明

| 数据块 | 数据来源 | 说明 |
| --- | --- | --- |
| raw_page / raw_page_meta | CDP 页面抓取 | 标题、正文、HTML、最终 URL、截图路径等 |
| cleaned | 页面原文 | 清洗后的正文和快速字段抽取 |
| external.qcc | 企查查 MCP（若配置） | 企业锚定、工商信息、风险信息；失败也会记录状态 |

如果没有 `qcc_config.json`，公司信息请求会跳过，`cleaned.json` 中不会附加 `external.qcc`。

## 使用流程

### 首次运行

```bash
python main.py "https://www.zhipin.com/job_detail/xxx.html"
```

脚本会：

1. 探测 `127.0.0.1:9222`，不在 → 用 `--remote-debugging-port=9222 --user-data-dir=.chrome-debug-profile/` 启动一个**可见的** Chrome 窗口，并直接打开目标 URL。
2. 检测到页面被跳转到登录页 → 在终端提示「请在 Chrome 窗口完成登录」。
3. 你登录完成后，脚本自动检测 URL 不再含 `/login`/`/web/user` 等关键字，再用 `Page.navigate` 把 tab 导回目标 URL。
4. 抓取 title / text / html → 清洗文本 → 若配置 `qcc_config.json`，调用企查查整合公司工商 / 风险数据 → 保存到 `data/<host_path>/`。

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
| `--no-screenshot` | 跳过整页截图 |
| `--login-wait SEC` | 等待用户首次登录的最大秒数（默认 600） |

## 输出

每个职位 URL 会稳定落在 `data/<host_path>/` 下；同一个页面地址会复用同一个目录，便于后续作为缓存使用。

| 文件 | 含义 |
| --- | --- |
| `raw_page.html` | 通过 CDP 拿到的页面 HTML（最多 400k 字符） |
| `raw_page_meta.json` | URL、final_url、标题、CDP 元数据（tab_source、launched_chrome 等） |
| `cleaned.json` | 清洗后的页面文本 + 字段快速抽取 + `external.qcc` 公司外部数据（若配置并成功/失败均会记录状态） |
| `qcc_raw.json` | QCC 锚定、工商、风险 tool 的完整原始结果汇总（仅在触发 QCC 请求时生成） |
| `summary.json` | 本次抓取与公司信息请求状态摘要 |
| `screenshot/job_*.png` | 全页截图（默认开启） |

## 当前测试模式

`main.py` 目前不会启动 `analyzers/` 下的子 agent，也不会生成 `analysis_*.json`。运行结果集中保存在 `raw_page.html`、`raw_page_meta.json`、`cleaned.json` 和 `summary.json` 中。

## 常见问题

**Q: 我已经在自己日常的 Chrome 里登录了 BOSS 直聘，脚本能复用吗？**
不能直接复用 —— CDP 走的是独立 profile（`.chrome-debug-profile/`），跟你日常 Chrome 是两个隔离的实例。在 CDP profile 里登录一次即可，之后 cookies 一直在那个目录里。

**Q: Chrome 窗口能最小化或者藏到后台吗？**
可以最小化，但不要关闭。每次脚本运行若发现 9222 没监听，就会重启 Chrome —— 也能用，只是多花几秒启动时间。

**Q: 想要 headless 模式怎么办？**
当前流程默认可见窗口，方便首次登录。如果你的 cookies 已经稳定，可以在 `cdp_scraper.launch_chrome_with_cdp` 的 args 里加 `"--headless=new"`。
