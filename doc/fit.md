# 前后端对接契约 (Fit)

> 给负责实现 FastAPI 后端 / API 适配层的开发者或 agent。
>
> 这份文档定义了**前端期望的 HTTP / SSE 接口契约**：URL、方法、请求/响应 JSON shape、字段语义。前端代码已经按这套契约写好（`frontend/src/app/core/services/api.service.ts`、`frontend/src/app/core/models/job.model.ts`），只要后端实现匹配，把 `frontend/src/environments/environment.ts` 里的 `useMock` 切成 `false` 即可联调，前端组件不需要任何改动。

---

## 1. 总览

| Method | Path                                       | 用途                                |
| ------ | ------------------------------------------ | ----------------------------------- |
| GET    | `/api/results`                             | 历史分析列表（drawer）              |
| GET    | `/api/results/{id}`                        | 单个职位分析详情                    |
| GET    | `/api/companies/{companyId}`               | 公司画像（modal）                   |
| POST   | `/api/analyze`                             | 提交一个新的分析任务                |
| POST   | `/api/results/{id}/reanalyze`              | 对已有结果重新运行分析              |
| GET    | `/api/analyze/{taskId}/stream` (SSE)       | 订阅任务进度                        |
| GET    | `/api/candidate-profile` ⚠️                  | 读取候选人画像（**前端尚未接入**）   |
| PUT    | `/api/candidate-profile` ⚠️                  | 写入候选人画像（**前端尚未接入**）   |

- 默认端口：`http://127.0.0.1:8000`（前端的 `environment.apiBase` 已经指向这里）
- 所有响应都用 JSON，编码 UTF-8，**不要给字段名做 camel/snake 转换**：前端类型与下面定义完全对齐
- **所有键名一律英文 camelCase**：JSON 里**禁止出现中文 key**（如 `{ "财务稳健性": 88 }` ❌），避免序列化、URL 参数、日志检索踩坑。中文只能作为字符串**值**出现（即用户可见的 label / 文案）
- 后端必须直接输出前端字段名，**不要指望前端 adapter 兜底**。例如分析生成时间字段必须是 `generatedAt`，不是 `generated_at`。
- CORS：需放行 `http://127.0.0.1:4200`（Angular dev server）
- ⚠️ 标注「前端尚未接入」的端点：前端 `ApiService` 已有候选人画像读写方法，但 `CandidateProfileComponent.save()` 目前仍仅 console.log，页面尚未真正调用保存；详见 §3.6 的「实施顺序提示」

---

## 2. 核心类型定义

以下所有类型都来自 `frontend/src/app/core/models/job.model.ts`，是**前端的事实**。后端可以选择：
- (A) 直接返回完全相同的 shape；**推荐**，省一层 adapter
- (B) 返回后端自己的 schema，由前端 `ApiService` 里做映射；**只在你的内部 schema 已经稳定且不愿意改时用**

### 2.1 维度系统

前端有 **6 个固定维度**，使用语义化英文键名，**顺序不可变**：

```ts
type DimensionId =
  | 'responsibility'    // 职责质量
  | 'requirements'      // 要求合理性
  | 'compensation'      // 薪酬福利
  | 'workload'          // 工作强度
  | 'companyHealth'     // 公司评分（与 company_risk_agent 语义对齐）
  | 'industryOutlook';  // 行业评分（与 industry_outlook_agent 语义对齐）

DIMENSIONS = [
  { id: 'responsibility',   name: '职责质量',   short: '职责' },
  { id: 'requirements',     name: '要求合理性', short: '要求' },
  { id: 'compensation',     name: '薪酬福利',   short: '薪酬' },
  { id: 'workload',         name: '工作强度',   short: '强度' },
  { id: 'companyHealth',    name: '公司评分',   short: '公司' },
  { id: 'industryOutlook',  name: '行业评分',   short: '行业' },
];
```

⚠️ LLM 原始输出的 schema 与前端 6 维定义必然存在不一致。怎么把 LLM 输出映射成下面这 6 个 key + 2 个顶层评分字段（可能涉及 prompt 调整、字段拼接、跨模块取值等），**由后端自己决定** —— fit 文档不指定路径。

**6 维度（落在 `JobAnalysis.scores` / `JobAnalysis.details` 里）：**

| 前端 key           | 中文名     | 语义来源 |
| ------------------ | ---------- | --- |
| `responsibility`   | 职责质量   | 职责描述清晰度 / 技术挑战明确程度 |
| `requirements`     | 要求合理性 | 硬性门槛 vs 薪资匹配 / 隐性门槛 |
| `compensation`     | 薪酬福利   | 现金 + 股权 + 福利的完备度与市场分位 |
| `workload`         | 工作强度   | 加班节奏 / WLB / 远程灵活 |
| `companyHealth`    | 公司评分   | 财务稳健 / 治理 / 口碑 / 风险 |
| `industryOutlook`  | 行业评分   | 行业增速 / 长短期前景 / 风险 |

**顶层评分字段（不在 `scores` 里，是 `JobAnalysis` 直接字段）：**

| 前端 key | 中文名 | 值要求 |
| --- | --- | --- |
| `total` | 综合评分 | 0-100 整数 |
| `grade` | 建议 / 星级 | `"A · 推荐投递"` 形式 —— 星级与一句话建议用 `·` 拼接，必须是单个字符串 |

### 2.2 `JobAnalysis`（单条职位分析）

```ts
interface JobAnalysis {
  id: string;            // 路径用，等同后端 slug（urlparse 后的 host_path）
  generatedAt?: string;  // 分析生成时间，后端从内部 generated_at 转成 camelCase 后输出；建议 ISO 字符串
  sourceUrl?: string;    // 原始职位链接，用于前端「重新分析」；历史数据缺失时可不返回
  title: string;         // 职位名（如 "高级前端工程师"）
  code: string;          // 短 code（如 "BYT-FE-2086"），来源可用 job 内部编号或 URL 末段
  level: string;         // 级别（"P6 / 7"），可空字符串
  matchTag: string;      // 匹配度 chip 文案，如 "高度匹配" / "较匹配" / "需评估"
  company: string;       // 公司 id（用作 GET /api/companies/{id} 的 key）

  meta: JobMetaItem[];   // 顶部图标条：城市 / 薪资 / 经验 / 学历 / 类型 / 团队
  summaryMeta: JobSummaryMeta;
  scores: Record<DimensionId, number>;  // 6 个 0-100 整数，键名严格 DimensionId 联合类型
  total: number;         // 0-100 综合
  grade: string;         // "A · 推荐投递" / "A+ · 强烈推荐" / "B · 谨慎考虑"
  miniLabel: string;     // Hero 区迷你卡片副标题，如 "字节跳动 · 前端"
  miniTag: MiniTag;      // Hero 区角标

  summary: string[];     // 2-3 段叙述，前端按段落渲染
  pros: string[];        // 4 条左右
  cons: string[];        // 4 条左右
  details: Record<DimensionId, DimensionDetail>;  // 6 维详情，键名严格 DimensionId 联合类型
}

interface JobMetaItem {
  ico: 'location' | 'salary' | 'exp' | 'edu' | 'type' | 'team';
  label: string;         // 显示文本
  isSalary?: boolean;    // ico === 'salary' 时设 true，前端高亮成橙色
}

interface JobSummaryMeta {
  type: string;          // "技术研发 / 前端"
  industry: string;      // "互联网 / 内容平台"
  edu: string;
  exp: string;
  headcount: string;     // "2 人"
  posted: string;        // "今天 09:21" / "3 天前"，前端不做时间解析直接展示
}

interface MiniTag {
  text: string;          // "推荐投递" / "强烈推荐" / "谨慎考虑"
  cls: 'badge-green' | 'badge-orange' | 'badge-neutral';
  // 颜色规则建议（让后端来决定哪个颜色）：
  //   total >= 80 → badge-green
  //   total >= 65 → badge-orange
  //   else        → badge-neutral
}

interface DimensionDetail {
  title: string;         // "职责清晰具体,技术挑战明确"
  text: string;          // 一段叙述（80-200 字）
  kpis: DimensionKpi[];  // 4 个 KPI 卡片
}

interface DimensionKpi {
  label: string;         // "职责条目数"
  val: string;           // "5"，注意是字符串，可以带单位（"38 字" / "P82"）
  sub: string;           // "行业均值 3.2"
}
```

`GET /api/results` 返回的是 `JobAnalysis[]`，可以**裁剪掉 `details` 字段**减小列表载荷（前端 drawer 只用到 `id` / `title` / `total` / `company` / `meta`）；列表项点击后再请求 `GET /api/results/{id}` 拉完整数据。

### 2.3 `Company`（公司画像）

```ts
interface Company {
  name: string;
  code: string;              // 内部短 code
  tags: string[];            // 2 个左右，如 ["独角兽", "互联网大厂"]
  meta: {
    size: string;            // "10000+ 人"
    stage: string;           // "已上市" / "C 轮后"
    founded: string;         // "2012"
    location: string;        // "北京海淀"
  };
  info: [string, string][];  // 键值对数组，按显示顺序排列
                             // 注意：tuple 左侧是「中文 label」字符串，不是对象 key，可以是中文
                             // 例：[["统一信用代码", "9111..."], ["法定代表人", "张三"], ...]
  scores: CompanyScores;     // 公司多维评分，键名严格如下
  desc: string;              // 公司简介一段话
  industry: {
    name: string;            // "互联网 / 内容平台"
    score: number;           // 0-100
    desc: string;            // 行业评价一段话
    metrics: { val: string; label: string }[];  // 3 个，如 [{val:"11.2%",label:"行业增速"}, ...]
  };
}

// 公司评分维度也是 6 个固定 key（与职位 6 维独立）
type CompanyScoreId =
  | 'financialStability'   // 财务稳健性
  | 'growth'               // 成长性
  | 'employeeReputation'   // 员工口碑
  | 'promotion'            // 晋升机会
  | 'management'           // 管理水平
  | 'techCulture';         // 技术氛围

// 注意是 Partial —— 后端可以只返回 6 个 key 中的子集（如某家公司没有员工口碑数据就不出该 key）
type CompanyScores = Partial<Record<CompanyScoreId, number>>;
```

前端 modal 按 `COMPANY_SCORE_DIMENSIONS` 顺序遍历这 6 个 key，缺失（`undefined`）的维度跳过不渲染。后端如果某条数据所有 6 个都没有，可以返回空对象 `{}`。

`companyId` 由后端选择稳定标识符（推荐用统一社会信用代码，但前端不假设格式）；只要满足「同一公司在多条 `JobAnalysis.company` 字段里出现相同值」即可，前端用它做 `GET /api/companies/{companyId}` 的 URL 段。

### 2.4 `AnalyzeProgressEvent`（SSE 事件）

```ts
interface AnalyzeProgressEvent {
  stage:
    | 'launching_chrome'   // 启动 Chrome
    | 'waiting_login'      // 等待用户在 Chrome 窗口完成登录（前端高亮提示）
    | 'scraping_job'       // 抓取职位页面
    | 'scraping_company'   // 抓取公司详情页
    | 'qcc_enrich'         // 调企查查 MCP
    | 'analyzing'          // LLM 分析中（4 个子模块共用此 stage）
    | 'done'               // 完成
    | 'error';             // 失败

  message: string;         // 给用户看的中文短句，前端原样显示
  detail?: string;         // 可选，stage='analyzing' 时建议填子 agent 名
                           //   ('job_value' | 'company_risk' | 'industry_outlook' | 'final_evaluation')
  percent?: number;        // 0-100 整数，驱动进度条
  slug?: string;           // stage='done' 时必填，前端用它跳 /results/:slug
}
```

---

## 3. 接口细节

### 3.1 `GET /api/results`

```http
GET /api/results
```

**Response 200**：`JobAnalysis[]`。

列表项可裁掉 `details` 字段以减小载荷（其它必填字段都保留），点击列表项时前端会用 `GET /api/results/{id}` 再拉完整详情。

---

### 3.2 `GET /api/results/{id}`

```http
GET /api/results/{id}
```

**Response 200**：完整 `JobAnalysis`。
**Response 404**：`{ "detail": "not found" }`。

`id` 与 `JobAnalysis.id` 字段一致，前端把它当不透明字符串处理。

---

### 3.3 `GET /api/companies/{companyId}`

```http
GET /api/companies/91110108551385082Q
```

**Response 200**：完整 `Company`。
**Response 404**：`{ "detail": "not found" }`。

`companyId` 与 `JobAnalysis.company` 字段一致 —— 前端拿到 `JobAnalysis.company` 后直接拼到 URL 里，不解析也不假设格式。

---

### 3.4 `POST /api/analyze`

```http
POST /api/analyze
Content-Type: application/json

{ "url": "https://www.zhipin.com/job_detail/xxx.html" }
```

**Response 202**：

```json
{ "taskId": "a1b2c3d4-..." }
```

`taskId` 是后续 SSE 端点的入参；前端拿到后立刻跳 `/jobs/:taskId` 订阅进度流。前端期望本端点**立即返回**（不等任务完成）。

---

### 3.4.1 `POST /api/results/{id}/reanalyze`

```http
POST /api/results/www.zhipin.com_job_detail_xxx.html/reanalyze
Content-Type: application/json

{}
```

**用途**：前端在详情页点击「重新分析」时调用。后端会基于该历史结果 `analysis.json.url` 重新跑完整流程，并返回新的 `taskId`，后续仍然通过 `GET /api/analyze/{taskId}/stream` 订阅进度。

**Response 202**：

```json
{ "taskId": "a1b2c3d4-..." }
```

**Response 404**：`{ "detail": "not found" }`，表示 `id` 对应的历史结果不存在，或历史结果里找不到原始 URL。

可选请求体：

```json
{ "url": "https://www.zhipin.com/job_detail/xxx.html" }
```

如果传入 `url`，后端以请求体 URL 为准；否则读取 `data/{id}/analysis.json` 里的 `url`。

**重新分析语义**

- 必须走完整抓取 → 页面清洗 → 公司数据整合 → 4 个 LLM analyzer → adapter 输出流程。
- 不复用 `data/{id}/analysis.json`、`job_cleaned.json`、`company.json` 等旧分析产物；同 slug 目录下旧产物会被本次结果覆盖。
- QCC / 公司信息仍保留缓存策略：如果 `data/_company_cache/{USCC}.json` 未过期且可读，后端直接复用公司缓存；只有缓存过期、缺失、解析失败或没有命中唯一公司时，才重新获取公司数据。
- 重新分析的核心目标是基于最新抓取内容和现有公司数据重新运行 LLM，因此会重新生成 `analysis.json`。
- 完成时 SSE `done.slug` 仍是可直接用于 `GET /api/results/{slug}` 的结果 id。若 URL 未变化，通常会覆盖同一个 slug。

前端对接建议：重新分析按钮调用本接口拿到 `taskId` 后，直接跳转到现有进度页 `/jobs/:taskId`，不需要新增一套进度展示逻辑。

---

### 3.5 `GET /api/analyze/{taskId}/stream` (SSE)

```http
GET /api/analyze/{taskId}/stream
Accept: text/event-stream
```

**SSE 帧格式**：

```
data: {"stage":"scraping_job","message":"抓取职位页面正文","percent":25}

data: {"stage":"analyzing","message":"LLM 分析：职位综合价值","detail":"job_value","percent":70}

event: done
data: {"stage":"done","message":"分析完成","percent":100,"slug":"www.zhipin.com_job_detail_xxx"}

```

帧约定（前端要求）：

- 普通帧用默认 `message` event（`data:` 行直接跟 JSON），前端通过 `EventSource.onmessage` 接收
- **完成时发一个具名 event `done`**：`event: done\ndata: {...}\n\n`；前端通过 `es.addEventListener('done', ...)` 监听以 close stream
- `error` 时发普通 `data:` 帧（`stage: 'error'`），前端会展示错误信息
- 每帧必须以两个换行结尾（`\n\n`），否则 EventSource 不会触发
- `done` 帧里的 `slug` 必须可作为 `GET /api/results/{slug}` 的 id 使用，前端会自动跳转到 `/results/:slug`

当检测到 Chrome 跳到 login 页时，发一帧 `{ stage: 'waiting_login', message: '请在 Chrome 窗口完成登录' }`，前端会把这个阶段高亮成橙色提示。

**当前 FastAPI 实现的真实进度流**

后端 `web/app.py` 会在 `POST /api/analyze` 后立即创建后台任务；任务内部调用 `main.analyze_url(..., progress_callback=...)`，由 CLI 主流程在真实节点上推送进度。前端只需要订阅同一个 `taskId` 的 SSE，不需要轮询。

典型事件顺序如下（某些阶段可能因数据情况略过，例如页面不需要登录时不会出现 `waiting_login`，职位页已经包含工商信息时可能不会明显停留在 `scraping_company`）：

```text
launching_chrome   5%   启动 Chrome 调试实例
scraping_job       20%  抓取职位页面正文
waiting_login      15%  请在 Chrome 窗口完成登录（仅登录/安全校验时出现）
scraping_job       35%  清洗职位页面正文
scraping_company   42%  抓取公司详情页
qcc_enrich         55%  企查查公司信息整合
analyzing          70%  LLM 分析：职位综合价值       detail=job_value
analyzing          80%  LLM 分析：公司风险           detail=company_risk
analyzing          88%  LLM 分析：行业前景           detail=industry_outlook
analyzing          95%  LLM 分析：综合评估           detail=final_evaluation
done               100% 分析完成                    slug=<resultId>
```

说明：

- `percent` 是展示用进度，不保证严格单调；例如进入登录等待时可能从 `20` 回到 `15`，前端可以直接展示最新帧，或自行取最大值。
- `waiting_login` 表示后端正在阻塞等待用户在本机 Chrome 完成登录/安全校验；前端应保持 SSE 连接，不要主动取消任务。
- `scraping_company` 阶段必须取得有效的 18 位统一社会信用代码；开始抓取时 `detail = "start"`，只有获取到 USCC 后才发送 `detail = "success"`。如果公司页未抓到 USCC，后端直接发送 `error`，不会进入 `qcc_enrich`。
- `qcc_enrich` 阶段只处理已经拿到 USCC 的公司数据查询；拿到有效 USCC 即表示企业实体已经锚定成功。
- `analyzing` 阶段通过 `detail` 区分具体子 agent：`job_value` / `company_risk` / `industry_outlook` / `final_evaluation`。
- `done` 必须是具名事件；前端收到后读取 `slug`，跳转到 `/results/:slug`，然后关闭 `EventSource`。
- `error` 使用普通 message 帧（不是具名事件），字段形如 `{ "stage": "error", "message": "...", "percent": 100, "detail": "scrape_error" }`；前端收到后展示错误并关闭连接即可。若 `detail = "company_uscc_unresolved"` 或 `detail = "company_info_failed"`，表示后端未能取得/锚定公司信息，任务不会执行 QCC 分析与 LLM 分析，不会生成 `analysis.json`，也不会发送 `done`。

**前端对接示例**

```ts
const es = new EventSource(`${apiBase}/api/analyze/${taskId}/stream`);

es.onmessage = (ev) => {
  const event = JSON.parse(ev.data) as AnalyzeProgressEvent;
  if (event.stage === 'error') {
    es.close();
    // 展示 event.message
    return;
  }
  // 更新当前阶段、message、percent、detail
};

es.addEventListener('done', (ev) => {
  const event = JSON.parse((ev as MessageEvent).data) as AnalyzeProgressEvent;
  es.close();
  // router.navigate(['/results', event.slug])
});
```

---

### 3.6 候选人画像 ⚠️ 前端尚未接入

> **当前状态**：前端 `frontend/src/app/core/services/api.service.ts` 已有 `getCandidateProfile()` / `updateCandidateProfile()` 方法；但 `CandidateProfileComponent.save()` 目前只 `console.log`，页面尚未真正调用保存。
>
> **实施顺序提示**：FastAPI agent 可以选择延后实现这两个端点（待前端补完 ApiService 调用后再做），或者先按下面定义实现以备前端接入。**两种顺序都可以**，但调用未接入端点不会立刻产生联调价值。

```http
GET /api/candidate-profile
```

**Response 200**：`candidate_profile.json` 的原始内容（结构见 `candidate_profile.example.json`）；文件不存在时返回 `404` 或 `200 + null`，前端会引导用户从模板创建。

```http
PUT /api/candidate-profile
Content-Type: application/json

{ "basic": {...}, "skills": {...}, "career_goals": {...}, "constraints": {...}, "preferences": {...} }
```

**Response 200**：`{ "ok": true }`。

⚠️ **中文 key 例外**：`candidate_profile.json` 内部字段（如 `basic.工作年限`、`skills.编程语言`）是**用户编辑的本地文件**，键名是中文 —— 这是文件历史约定，**仅此端点透传时允许中文 key**。前端接入时会用 `Record<string, any>` / `unknown` 透传，不强类型化。这条例外不适用于其他任何端点。

---

## 4. 字段值要求提示

下面是前端对**特定字段值形态**的硬要求 —— 后端怎么拿到这些值由你决定，但拿到后必须符合这些约束：

- **`grade`** 必须是**单个字符串**，形式 `"A · 推荐投递"` —— 星级和一句话建议用 ` · ` 拼接。不要把它拆成两个字段返回。
- **`miniTag.cls`** 必须根据 `total` 落桶：`total >= 80` → `badge-green`；`total >= 65` → `badge-orange`；其它 → `badge-neutral`。
- **`scores[*]`** 是 0-100 **整数**（前端按整数渲染；浮点数会被截断）。
- **`details[*].kpis`** 长度**期望 4**（多于 4 会被前端截断显示前 4 个）。
- **`Company.info`** 是 `[label, value]` tuple 数组，按显示顺序排列；左侧 label 是用户可见的中文字符串（不是 object key）。
- **`AnalyzeProgressEvent.percent`** 是 0-100 整数。
- **`AnalyzeProgressEvent.slug`** 在 `stage === "done"` 帧必填，必须可直接作为 `GET /api/results/{slug}` 的 id 使用。

`Company.scores` 是 `Partial<Record<CompanyScoreId, number>>`，可以只返回部分 key（详见 §2.3）。其它所有 `JobAnalysis` / `Company` 字段都是必填（见类型定义）。

如果跑通后某些字段确实拿不到合理值（例如某条数据公司未做风险分析），返回类型层允许的空值即可：字符串字段返回 `""`、数组字段返回 `[]`、数字字段返回 `0`。前端有兜底渲染。

---


## 5. 测试用样本

`frontend/src/app/core/mock/jobs.mock.ts` 里有 3 个职位 + 3 家公司的完整 mock 数据。**实现完后端后**，建议拿其中一条直接 hard-code 成响应跑通一次，再接真实管线。这样能快速隔离「实现错」和「数据错」两类问题。

---

## 6. 不要做的事

- ❌ 不要修改 `JobAnalysis` / `Company` 类型定义来迎合后端 —— 类型是前端的事实，请用 adapter 函数收口差异
- ❌ 不要在 SSE 帧里漏 `stage` 字段，或用前端没声明的 stage 值
- ❌ 不要在任何字段名（object key）里出现中文 —— 包括 `scores` / `details` / 任何嵌套对象。中文只允许作为字符串「值」存在（用户可见 label / 文案）
  - 职位维度 key 必须用 `responsibility` / `requirements` / `compensation` / `workload` / `companyHealth` / `industryOutlook`
  - 公司评分 key 必须用 `financialStability` / `growth` / `employeeReputation` / `promotion` / `management` / `techCulture`
  - 任何 `Record<string, X>` 类型字段，后端也得保证 key 是英文 camelCase
- ❌ 不要给字段名做 camelCase ↔ snake_case 转换；前端是 camelCase（`taskId` / `matchTag` / `miniLabel` / `generatedAt` / `companyHealth` / `industryOutlook` / `financialStability`），后端响应直接用 camelCase
  - 例如内部持久化字段可以叫 `generated_at`，但 HTTP JSON 必须返回 `generatedAt`
- ❌ 不要破坏「`POST /api/analyze` 立即返回 + SSE 推进度」的异步模型；不要返回阻塞的同步响应

---

## 7. 联调步骤

1. 后端实现完接口，跑起来在 `:8000`
2. 前端 `frontend/src/environments/environment.ts` 改 `useMock: false`
3. `cd frontend && npx ng serve`
4. 浏览器打开 `http://127.0.0.1:4200`，看 drawer 是否能拉到列表、点击是否能进详情
5. 试一次 `POST /api/analyze`：输入 URL，提交后进度页应该按 SSE 事件流动

如果某条接口返回的 shape 跟前端期望对不上，**优先改后端 adapter**，不要改前端组件。
