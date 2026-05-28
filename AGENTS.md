# AGENTS.md

> 给负责实现 FastAPI 后端 / API 适配层的 agent 看。
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
| GET    | `/api/analyze/{taskId}/stream` (SSE)       | 订阅任务进度                        |
| GET    | `/api/candidate-profile`                   | 读取候选人画像                      |
| PUT    | `/api/candidate-profile`                   | 写入候选人画像                      |

- 默认端口：`http://127.0.0.1:8000`（前端的 `environment.apiBase` 已经指向这里）
- 所有响应都用 JSON，编码 UTF-8，**不要给字段名做 camel/snake 转换**：前端类型与下面定义完全对齐
- **所有键名一律英文 camelCase**：JSON 里**禁止出现中文 key**（如 `{ "财务稳健性": 88 }` ❌），避免序列化、URL 参数、日志检索踩坑。中文只能作为字符串**值**出现（即用户可见的 label / 文案）
- CORS：需放行 `http://127.0.0.1:4200`（Angular dev server）

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

⚠️ 后端 `analyzers/` 目前是 **3 + 1 模型**（job_value / company_risk / industry_outlook / final）。后端必须做**字段映射**：

**6 维度（落在 `JobAnalysis.scores` / `JobAnalysis.details` 里）：**

| 前端 key           | 中文名     | 来源 analyzer       | 字段建议                                  |
| ------------------ | ---------- | ------------------- | ----------------------------------------- |
| `responsibility`   | 职责质量   | `job_value`         | `job_value.analysis.维度.职责.分数`       |
| `requirements`     | 要求合理性 | `job_value`         | `job_value.analysis.维度.要求.分数`       |
| `compensation`     | 薪酬福利   | `job_value`         | `job_value.analysis.维度.薪酬.分数`       |
| `workload`         | 工作强度   | `job_value`         | `job_value.analysis.维度.强度.分数`       |
| `companyHealth`    | 公司评分   | `company_risk`      | `company_risk.analysis.综合评分.分数`     |
| `industryOutlook`  | 行业评分   | `industry_outlook`  | `industry_outlook.analysis.综合评分.分数` |

**顶层评分字段（不在 `scores` 里，是 `JobAnalysis` 直接字段）：**

| 前端 key | 中文名     | 来源 analyzer      | 字段建议                                |
| -------- | ---------- | ------------------ | --------------------------------------- |
| `total`  | 综合评分   | `final_evaluation` | `final.analysis.综合评分.分数`          |
| `grade`  | 建议 / 星级 | `final_evaluation` | `final.analysis.星级` 或 `建议动作`     |

具体字段路径以 `analyzers/*.py` 的 `EXPECTED_KEYS` 为准；如果 analyzer 输出 schema 调整了，请同步更新这两张映射表。

### 2.2 `JobAnalysis`（单条职位分析）

```ts
interface JobAnalysis {
  id: string;            // 路径用，等同后端 slug（urlparse 后的 host_path）
  title: string;         // 职位名（如 "高级前端工程师"）
  code: string;          // 短 code（如 "BYT-FE-2086"），来源可用 job 内部编号或 URL 末段
  level: string;         // 级别（"P6 / 7"），可空字符串
  matchTag: string;      // 匹配度 chip 文案，如 "高度匹配" / "较匹配" / "需评估"
  company: string;       // 公司 id（用作 GET /api/companies/{id} 的 key）

  meta: JobMetaItem[];   // 顶部图标条：城市 / 薪资 / 经验 / 学历 / 类型 / 团队
  summaryMeta: JobSummaryMeta;
  scores: Record<DimensionId, number>;  // 6 个 0-100 整数，键名严格 d0..d5
  total: number;         // 0-100 综合
  grade: string;         // "A · 推荐投递" / "A+ · 强烈推荐" / "B · 谨慎考虑"
  miniLabel: string;     // Hero 区迷你卡片副标题，如 "字节跳动 · 前端"
  miniTag: MiniTag;      // Hero 区角标

  summary: string[];     // 2-3 段叙述，前端按段落渲染
  pros: string[];        // 4 条左右
  cons: string[];        // 4 条左右
  details: Record<DimensionId, DimensionDetail>;  // 6 维详情，键名严格 d0..d5
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

type CompanyScores = Record<CompanyScoreId, number>;
```

后端可以选择只返回部分 key（如某家公司没有员工口碑数据），前端按 `COMPANY_SCORE_DIMENSIONS` 顺序遍历、缺失即跳过。

`companyId` 的命名约定：用 `_company_cache/<uscc>.json` 里的 `uscc`（统一社会信用代码）。前端不假设 id 格式，但建议保持稳定。

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

**Response 200**：`JobAnalysis[]`（可裁掉 `details` 字段）

实现建议：扫描 `data/<slug>/` 目录，每个目录读 `job_cleaned.json` + `analysis.json` + `summary.json`，合并后塞进数组返回。

---

### 3.2 `GET /api/results/{id}`

```http
GET /api/results/{slug}
```

**Response 200**：完整 `JobAnalysis`
**Response 404**：`{ "detail": "not found" }`

`id` 就是 `data/` 下的目录名（slug），即 `slugify_url(url)` 的输出。

---

### 3.3 `GET /api/companies/{companyId}`

```http
GET /api/companies/91110108551385082Q
```

**Response 200**：完整 `Company`
**Response 404**：`{ "detail": "not found" }`

数据源：`data/_company_cache/<uscc>.json`。如果 cache 里没有 score / industry 字段（这是 LLM 出的），后端需要按 `company_risk_agent` + `industry_outlook_agent` 的输出来填充。

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

实现建议：

- 生成 `taskId`（uuid4）
- 用 `asyncio.create_task` 在后台跑 `main.analyze_url(url)`
- 把进度通过一个 `asyncio.Queue` / `anyio.MemoryObjectStream` 暴露给后续 SSE 端点
- **立即**返回 taskId，不要等任务完成

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

注意点：

- 普通帧用默认 `message` event（`data:` 行直接跟 JSON）；前端通过 `EventSource.onmessage` 接收
- **完成时发一个具名 event `done`**：`event: done\ndata: {...}\n\n`；前端通过 `es.addEventListener('done', ...)` 监听这个事件来 close stream
- `error` 时发普通 `data:` 帧即可（`stage: 'error'`），前端会展示错误信息
- 每帧必须以**两个换行**结尾（`\n\n`），否则 EventSource 不会触发
- 建议 FastAPI 用 `EventSourceResponse`（来自 `sse-starlette`）实现

**抓取登录提示**：当检测到 Chrome 跳到 login 页时，发一帧 `{ stage: 'waiting_login', message: '请在 Chrome 窗口完成登录' }`，前端会把这个阶段高亮成橙色提示。

---

### 3.6 候选人画像

```http
GET /api/candidate-profile
```

**Response 200**：直接返回 `candidate_profile.json` 的原始内容（结构见 `candidate_profile.example.json`）；如果文件不存在返回 `404` 或 `200 + null`，前端会引导用户从模板创建。

```http
PUT /api/candidate-profile
Content-Type: application/json

{ "basic": {...}, "skills": {...}, "career_goals": {...}, "constraints": {...}, "preferences": {...} }
```

**Response 200**：`{ "ok": true }`

实现建议：先 validate（缺字段允许、多字段拒绝），写入项目根目录的 `candidate_profile.json`。

---

## 4. 字段映射的实操建议

`analyzers/` 现有输出和前端期望之间最大的 gap 是「3+1 模块 → 6 维度评分 + 顶层评分 + 一堆展示字段」。落地步骤：

1. 在后端写一个**纯函数** `to_job_analysis(slug, summary, job_cleaned, analysis_bundle) -> dict`，输出严格符合前面定义的 `JobAnalysis` shape
2. 同样写一个 `to_company(uscc, qcc_block, risk_analysis, industry_analysis) -> dict` 出 `Company` shape
3. 这两个函数集中处理所有字段名差异（中文 → 英文 camelCase、嵌套 → 扁平、LLM 多键拼接、颜色阈值规则等）
4. 不要让 analyzer 原始输出直接漏到 HTTP 层 —— 这样以后调 prompt 或换模型时 schema 不会污染前端

### ⚠️ 阅读伪代码前必须知道的事

下面伪代码里的「LLM 输出字段名」（如 `jv[<职责子项>]`、`final["星级"]`）**全部是占位指引，不是真实路径**。原因：

- `analyzers/*.py` 里每个 agent 的 `EXPECTED_KEYS` 还在 prompt 调整中（README 已说明主流程暂时屏蔽 LLM）
- 实际字段路径以仓库 `analyzers/<agent>.py` 顶部的 `EXPECTED_KEYS` 元组为**唯一真相源**，例如：
  - `job_value_agent.EXPECTED_KEYS = ("岗位画像", "维度评分", "职责与产出", ...)`
  - `company_risk_agent.EXPECTED_KEYS = ("公司画像", "统一评分", "风险明细", ...)`
  - `industry_outlook_agent.EXPECTED_KEYS` （单行业模式）/ `MULTI_INDUSTRY_EXPECTED_KEYS` （多行业模式）
  - `final_evaluation_agent.EXPECTED_KEYS = ("综合评分", "星级", "岗位画像", "申请建议", "markdown_summary", ...)`
- 伪代码用 `<...>` 标注「这里要填实际 LLM 输出的子字段名」，请对照当时的 `EXPECTED_KEYS` 实现

如果 prompt 改了 → 改 adapter，**不要改前端类型**。

### `to_job_analysis` 完整字段映射

```python
def to_job_analysis(slug: str, summary: dict, job_cleaned: dict, analysis: dict) -> dict:
    """
    输入：
      slug            目录名（data/<slug>/）
      summary         summary.json 内容（含 final_url / company_enrichment 等）
      job_cleaned     job_cleaned.json 内容（页面清洗后的中文字段）
      analysis        analysis.json 内容（{ modules: {...}, final: {...} }）
    输出：严格符合前端 JobAnalysis 类型，所有字段都填。
    """
    jv    = analysis["modules"]["job_value"]["analysis"]
    cr    = analysis["modules"]["company_risk"]["analysis"]
    io    = analysis["modules"]["industry_outlook"]["analysis"]
    final = analysis["final"]["analysis"]

    # company id：直接复用 company.json 的引用规则（uscc 或 company_name）
    company_id = summary.get("company_enrichment", {}).get("anchor", {}).get("统一社会信用代码", "")

    total = int(final[<综合评分子项>]["分数"])  # 实际 key 见 final_evaluation_agent.EXPECTED_KEYS

    return {
        # —— 标识 ——
        "id":        slug,
        "code":      _short_code_from_url(summary.get("url", "")),  # 自己生成短码，如 "BYT-FE-2086"

        # —— 来自 job_cleaned 的页面字段（直接搬）——
        "title":     job_cleaned.get("职位名称", ""),
        "level":     job_cleaned.get("职级", ""),                  # 可空

        # —— 来自 LLM final（匹配建议）——
        "matchTag":  final[<匹配标签子项>],                          # 如 "高度匹配" / "较匹配" / "需评估"
        "grade":     f'{final["星级"]} · {final[<申请建议短语>]}',   # 拼接："A · 推荐投递"

        # —— 关联 Company ——
        "company":   company_id,

        # —— 顶部 meta 图标条（来自 job_cleaned，按固定顺序组装）——
        "meta": [
            {"ico": "location", "label": job_cleaned.get("职位工作地点", "")},
            {"ico": "salary",   "label": job_cleaned.get("薪资", ""), "isSalary": True},
            {"ico": "exp",      "label": job_cleaned.get("要求年限", "")},
            {"ico": "edu",      "label": job_cleaned.get("学历要求", "")},
            {"ico": "type",     "label": "全职"},                    # 如 cleaned 没区分就 hard-code
            {"ico": "team",     "label": jv.get(<团队/方向短语>, "")},
        ],

        # —— Hero 区迷你卡片 ——
        "miniLabel": f'{<公司名>} · {<职能简称>}',
        "miniTag":   _mini_tag(total),  # 见下方颜色阈值函数

        # —— 综合解读区的「基本信息」块 ——
        "summaryMeta": {
            "type":      jv.get(<职位类型>, ""),                     # "技术研发 / 前端"
            "industry":  io.get(<行业名称>, ""),
            "edu":       job_cleaned.get("学历要求", ""),
            "exp":       job_cleaned.get("要求年限", ""),
            "headcount": job_cleaned.get("招聘人数", ""),
            "posted":    job_cleaned.get("发布时间", ""),
        },

        # —— 6 维分数（映射规则见 §2.1 表）——
        "scores": {
            "responsibility":  int(jv[<维度评分>][<职责子项>]["分数"]),
            "requirements":    int(jv[<维度评分>][<要求子项>]["分数"]),
            "compensation":    int(jv[<维度评分>][<薪酬子项>]["分数"]),
            "workload":        int(jv[<维度评分>][<强度子项>]["分数"]),
            "companyHealth":   int(cr[<统一评分子项>]["分数"]),       # company_risk 用 "统一评分"
            "industryOutlook": int(_industry_score(io)),             # 见下方双模式辅助
        },

        # —— 顶层综合 ——
        "total": total,
        # grade 已在上方拼接

        # —— 综合解读区的叙述 ——
        "summary": final.get("markdown_summary", "").split("\n\n")[:2],  # 或拆 final 的「岗位画像」段落
        "pros":    list(final.get(<优势亮点子项>, []))[:4],
        "cons":    list(final.get(<潜在风险子项>, []))[:4],

        # —— 6 维详情（每维 1 段叙述 + 4 个 KPI 卡）——
        "details": {
            "responsibility":  _build_detail(jv, <职责子项>),
            "requirements":    _build_detail(jv, <要求子项>),
            "compensation":    _build_detail(jv, <薪酬子项>),
            "workload":        _build_detail(jv, <强度子项>),
            "companyHealth":   _build_detail(cr, <公司画像/风险明细>),
            "industryOutlook": _build_detail(io, <行业格局/趋势驱动>),
        },
    }


def _mini_tag(total: int) -> dict:
    """颜色阈值规则，与 §2.2 MiniTag 注释保持一致。"""
    if total >= 80:
        return {"text": "推荐投递", "cls": "badge-green"}
    if total >= 65:
        return {"text": "可以考虑", "cls": "badge-orange"}
    return {"text": "谨慎考虑", "cls": "badge-neutral"}


def _industry_score(io: dict) -> int:
    """industry_outlook 双模式：单行业 vs 多行业。"""
    if "综合评估" in io:                  # MULTI_INDUSTRY_EXPECTED_KEYS 模式
        return int(io["综合评估"]["分数"])
    # 单行业模式：从短期/长期前景或自定义 key 取
    return int(io[<单行业评分子项>]["分数"])


def _build_detail(module_analysis: dict, dim_key: str) -> dict:
    """
    把 LLM 某维度的输出拆成 DimensionDetail。
    KPI 数量固定 4 张：要么 prompt 让 LLM 直接输出 [{label,val,sub} x4]；
    要么 adapter 从叙述长文本里抽数字 + label 拼出来。建议前者。
    """
    sub = module_analysis[dim_key]
    return {
        "title": sub.get("小结", ""),
        "text":  sub.get("分析", ""),
        "kpis":  sub.get("kpi卡片", [])[:4],  # 4 张固定
    }
```

### `to_company` 完整字段映射

```python
def to_company(uscc: str, qcc_block: dict, risk_analysis: dict, industry_analysis: dict) -> dict:
    """
    输入：
      uscc                  统一社会信用代码（作为 companyId）
      qcc_block             qcc_block["cleaned"] —— 来自 _company_cache/<uscc>.json
                            ⚠️ 内部字段是 QCC MCP 返回的【中文 key】，例如
                               "企业名称" / "法定代表人" / "企业规模" / "成立日期" / "注册地址" / ...
                            实际 key 名以 external_data/qcc_client.py 输出为准。
      risk_analysis         company_risk_agent 的 analysis（含 "统一评分" / "风险明细" 等中文键）
      industry_analysis     industry_outlook_agent 的 analysis
    输出：严格符合前端 Company 类型。
    """
    cr = risk_analysis
    name     = qcc_block.get("企业名称", "")
    legal    = qcc_block.get("法定代表人", "")
    size     = qcc_block.get("企业规模", "")
    founded  = qcc_block.get("成立日期", "")[:4]          # 只要年份
    location = _short_location(qcc_block.get("注册地址", ""))  # "北京海淀" 这种

    return {
        "name": name,
        "code": _short_code_for_company(name),    # 自己生成，如 "BYT-2012"

        # tags / stage：QCC 没有，需要 company_risk_agent 输出或基于规则推断
        "tags":  list(cr.get(<企业标签子项>, []))[:2],   # 如 ["独角兽", "互联网大厂"]
        "meta": {
            "size":     size,
            "stage":    cr.get(<融资阶段/上市状态>, ""),  # "已上市" / "C 轮后"
            "founded":  founded,
            "location": location,
        },

        # info：[中文 label, 值] 的有序 tuple 数组（左侧 label 允许中文，是显示文本不是 key）
        "info": [
            ["统一信用代码", uscc],
            ["法定代表人",   legal],
            ["注册资本",     qcc_block.get("注册资本", "")],
            ["参保人数",     qcc_block.get("参保人数", "")],
            ["公司主页",     qcc_block.get("公司主页", "")],
            ["在招职位",     qcc_block.get("在招职位数", "")],
        ],

        # 6 个固定英文 key —— 详细映射见 §2.3
        "scores": {
            "financialStability": int(cr[<财务稳健性子项>]["分数"]),
            "growth":             int(cr[<成长性子项>]["分数"]),
            "employeeReputation": int(cr[<员工口碑子项>]["分数"]),
            "promotion":          int(cr[<晋升机会子项>]["分数"]),
            "management":         int(cr[<管理水平子项>]["分数"]),
            "techCulture":        int(cr[<技术氛围子项>]["分数"]),
        },

        "desc": cr.get(<公司简介>, "") or qcc_block.get("企业简介", ""),

        "industry": {
            "name":    industry_analysis[<行业识别>]["行业名称"],
            "score":   int(_industry_score(industry_analysis)),
            "desc":    industry_analysis.get(<行业说明>, ""),
            "metrics": [
                {"val": industry_analysis[<增速>],     "label": "行业增速"},
                {"val": industry_analysis[<薪资中位>], "label": "薪资中位数"},
                {"val": industry_analysis[<从业规模>], "label": "从业人数"},
            ],
        },
    }
```

### 关键点小结

- **`grade` 必须是拼接结果**：前端展示 `"A · 推荐投递"`，需要 adapter 用 `f'{星级} · {申请建议}'` 拼好，不要分两个字段返回
- **`miniTag` 由后端按阈值决定**：颜色规则 `>=80 green / >=65 orange / <65 neutral`，集中在 `_mini_tag()` 实现
- **`industryOutlook` 评分要兼容双模式**：`io` 可能是 `EXPECTED_KEYS`（单行业）或 `MULTI_INDUSTRY_EXPECTED_KEYS`（多行业），用 `_industry_score()` 适配
- **`kpis` 字段固定 4 张**：强烈建议改 prompt 让 LLM 直接输出 `[{label, val, sub} x 4]`；如果 prompt 不动，就要 adapter 从叙述里抽数字硬拼，会很脏
- **公司侧 QCC 字段都是中文**：`qcc_block` 来自 `qcc_client.py`，字段名形如 `企业名称` / `法定代表人` / `成立日期` —— 不是英文 camelCase，**不要假设有 `name` / `legalRep` 这类英文 key**
- **`tags` / `stage`**：QCC 没这两个，必须由 `company_risk_agent` 的 prompt 输出，或后端用规则推断（如有「上市」字眼 → stage="已上市"）
- **`code` 都是内部短码**：职位 `BYT-FE-2086`、公司 `BYT-2012` 这种，QCC 和 LLM 都不提供，后端自己生成（取公司名首字母 + URL job_id 等）

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
- ❌ 不要给字段名做 camelCase ↔ snake_case 转换；前端是 camelCase（`taskId` / `matchTag` / `miniLabel` / `companyHealth` / `industryOutlook` / `financialStability`），后端响应直接用 camelCase
- ❌ 不要破坏「`POST /api/analyze` 立即返回 + SSE 推进度」的异步模型；不要返回阻塞的同步响应

---

## 7. 联调步骤

1. 后端实现完接口，跑起来在 `:8000`
2. 前端 `frontend/src/environments/environment.ts` 改 `useMock: false`
3. `cd frontend && npx ng serve`
4. 浏览器打开 `http://127.0.0.1:4200`，看 drawer 是否能拉到列表、点击是否能进详情
5. 试一次 `POST /api/analyze`：输入 URL，提交后进度页应该按 SSE 事件流动

如果某条接口返回的 shape 跟前端期望对不上，**优先改后端 adapter**，不要改前端组件。
