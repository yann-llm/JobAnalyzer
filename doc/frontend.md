# 前端工作总结

> 截至 PR #2 合并的前端阶段性产物概览。本文档面向需要了解前端架构、扩展页面、对接后端的开发者。

## 1. 技术选型

| 项 | 选型 | 说明 |
| --- | --- | --- |
| 框架 | Angular 19 | standalone components，无 NgModule |
| UI 库 | Angular Material 19 + CDK | 仅用功能组件（Dialog / Form / Expansion 等），样式套自定义主题 |
| 状态 | Signals + `toSignal` + `computed` | 不引入 NgRx，组件级 signal 足够 |
| 路由 | `@angular/router` lazy-load + `RouterLink(Active)` | 4 条路由，全部 standalone component 懒加载 |
| 数据获取 | `HttpClient` (fetch backend) + `EventSource` (SSE) | 由 `ApiService` 统一收口 |
| 样式 | SCSS + CSS 变量 | 设计 token 全集中在 `styles.scss`，组件 scope 化 |
| 字体 | Inter（display + body）+ JetBrains Mono | 通过 Google Fonts CDN 引入 |
| 构建 | esbuild（Angular CLI 19 默认）| `npx ng build`，无需 webpack 配置 |

**为什么是 Material 但样式不像 Material**：原型 [`index.html`](../index.html) 是定制的紫色品牌风格（接近 Anthropic 配色），跟 Material 默认风格不一致。最终选「路线 A」—— Material 只用其功能组件（dialog 弹层、form 控件、expansion 面板），所有视觉规则（color / typography / spacing）由我们的 CSS 变量主题覆盖，确保和原型一致。

## 2. 目录结构

```
frontend/
├── angular.json
├── package.json
├── tsconfig*.json
├── src/
│   ├── index.html                              ← 应用入口 HTML（注入字体 + <app-root>）
│   ├── main.ts
│   ├── styles.scss                             ← 全局：Material 主题 + CSS 变量 + 工具类
│   ├── environments/
│   │   ├── environment.ts                      ← 开发：useMock: true, apiBase 指向 :8000
│   │   └── environment.prod.ts                 ← 生产：useMock: false
│   └── app/
│       ├── app.config.ts                       ← 全局 providers（Router / Animations / HttpClient）
│       ├── app.routes.ts                       ← 4 条路由全部 lazy-load
│       ├── app.component.{ts,html,scss}        ← 仅一个 <router-outlet>
│       │
│       ├── core/                               ── 数据层 ──
│       │   ├── models/
│       │   │   └── job.model.ts                ← 全部类型 + DIMENSIONS / COMPANY_SCORE_DIMENSIONS 常量
│       │   ├── mock/
│       │   │   └── jobs.mock.ts                ← 3 个职位 + 3 家公司样本（迁自 index.html）
│       │   └── services/
│       │       └── api.service.ts              ← mock / 真实 API 切换；SSE 桩
│       │
│       ├── shared/                             ── 可复用 ──
│       │   ├── score-utils.ts                  ← scoreClass / scoreCssVar：分数 → 颜色
│       │   └── radar-chart/                    ← SVG 雷达图（迷你版 + 大版共用）
│       │
│       ├── layout/                             ── 布局壳 ──
│       │   ├── app-shell/                      ← .app flex 容器，包含 drawer + router-outlet
│       │   └── drawer/                         ← 左侧 260px 历史列表
│       │
│       └── features/                           ── 路由级页面 ──
│           ├── dashboard/                      ← 主页（/ 与 /results/:id 共用）
│           │   ├── dashboard.component.*       ← 编排：拉数据、传给 4 个子区块
│           │   ├── hero-search/                ← URL 输入 + 迷你雷达卡
│           │   ├── job-card/                   ← 职位 header + meta + 操作按钮
│           │   ├── score-overview/             ← 环形评分图 + 6 维卡片
│           │   ├── analysis-tabs/              ← 综合解读 + 6 维详情 sub-tab
│           │   └── company-modal/              ← Material Dialog 公司画像
│           ├── submit-progress/                ← /jobs/:taskId SSE 进度页（保留的独立入口）
│           └── candidate-profile/              ← /profile 候选人画像编辑
```

## 3. 架构分层

四层职责清晰，自下而上：

```
┌─────────────────────────────────────────────┐
│  features/  ←  路由级页面（编排、消费数据）  │
├─────────────────────────────────────────────┤
│  layout/    ←  外壳、跨页元素（drawer 等）   │
├─────────────────────────────────────────────┤
│  shared/    ←  无业务的可复用组件 + 工具    │
├─────────────────────────────────────────────┤
│  core/      ←  数据模型 + Service + Mock    │
└─────────────────────────────────────────────┘
```

**关键原则：**

- `core` 是唯一数据来源 —— 所有页面通过 `ApiService` 获取数据，绝不直接 import mock 文件
- `core/mock` 与 `ApiService` 是兄弟关系，由 `environment.useMock` 切换；组件层完全无感
- `shared` 不依赖业务类型 —— 例外是 `radar-chart` 依赖 `DimensionId`，因为雷达图天然就是 6 维结构
- `features` 不互相 import；`dashboard` 子组件之间用 input/output 通信
- 类型定义只在 `core/models/job.model.ts`，组件 import `type { ... }`

## 4. 路由

| 路径 | 组件 | 用途 |
| --- | --- | --- |
| `/` | `DashboardComponent` | 默认展示历史中第一条职位的完整分析 |
| `/results/:id` | `DashboardComponent` | 指定职位的分析（drawer 点击触发） |
| `/jobs/:taskId` | `SubmitProgressComponent` | SSE 进度页 |
| `/profile` | `CandidateProfileComponent` | 候选人画像编辑 |

全部用 `loadComponent: () => import(...)` 懒加载，初始 bundle 仅含 `AppShellComponent` + `DrawerComponent` + 共享代码。Dashboard / Submit-progress / Candidate-profile 各自独立 chunk。

`AppShellComponent` 包含 drawer + `<router-outlet>`，是 4 条路由的父级；切换路由只换 outlet 内容，drawer 不重渲染（高亮项变化通过 `RouterLinkActive` 触发）。

## 5. 数据模型 & 评分维度

完整契约在根目录 `AGENTS.md`，这里只摘核心：

### `JobAnalysis` —— 一条职位分析

```ts
interface JobAnalysis {
  id: string;          // 对应 data/<slug>/ 目录名
  title: string;
  sourceUrl?: string;  // 原始职位链接，用于重新分析
  code: string;        // 内部短码
  level: string;
  matchTag: string;    // "高度匹配" / "较匹配" / "需评估"
  company: string;     // 公司 id，关联到 Company

  meta: JobMetaItem[];          // 顶部图标条
  summaryMeta: JobSummaryMeta;  // 综合解读区基本信息
  scores: Record<DimensionId, number>;  // 6 维 0-100
  total: number;       // 综合 0-100
  grade: string;       // "A · 推荐投递" 等

  miniLabel: string;
  miniTag: MiniTag;

  summary: string[];   // 叙述段落
  pros: string[];
  cons: string[];
  details: Record<DimensionId, DimensionDetail>;  // 6 维详情
}
```

### 6 维评分系统（`DimensionId`）

| Key | 中文名 | 来源 analyzer |
| --- | --- | --- |
| `responsibility` | 职责质量 | `job_value` |
| `requirements` | 要求合理性 | `job_value` |
| `compensation` | 薪酬福利 | `job_value` |
| `workload` | 工作强度 | `job_value` |
| `companyHealth` | 公司评分 | `company_risk` |
| `industryOutlook` | 行业评分 | `industry_outlook` |

**命名规则：**
- 全部英文 camelCase，禁止任何中文 key 出现在 JSON 序列化中
- `companyHealth` / `industryOutlook` 后缀避免与 `JobAnalysis.company`（关联 id 字段）混淆
- 顺序固定（雷达图、子 tab、卡片 grid 都依赖 `DIMENSIONS` 数组顺序）

### Company 多维评分（`CompanyScoreId`）

另一组独立 6 维，modal 内展示：

`financialStability` · `growth` · `employeeReputation` · `promotion` · `management` · `techCulture`

## 6. 组件设计

### Dashboard 子组件协作

```
DashboardComponent
├── 通过 ActivatedRoute.paramMap + toSignal 响应路由变化
├── 调 ApiService.getResult(id) 拉详情
├── 把 JobAnalysis 通过 input.required 传给：
│   ├── <jb-hero-search [job]="j" />            ← URL 输入 + 迷你雷达
│   ├── <jb-job-card [job]="j" (openCompany)>   ← 职位 header
│   ├── <jb-score-overview [job]="j" />         ← 环形图 + 6 维卡片
│   └── <jb-analysis-tabs [job]="j" />          ← 综合解读 + 维度详情
└── 监听 job-card 的 openCompany 事件 → MatDialog 弹 <jb-company-modal />
```

子组件都是纯展示 + 局部交互（如 analysis-tabs 自带 `active` signal 切换 tab），不持有业务数据。

### Radar Chart 实现

直接搬 `index.html` 的 `buildRadar()` 算法，用 SVG `<polygon>` + `<line>` 渲染：

- 4 圈背景（25% / 50% / 75% / 100%）
- 6 条辐条 + 6 个短名 label
- 数据 polygon（半透明紫填充 + 实线描边）
- 数据点（紫色圆点）

输入：`scores: Record<DimensionId, number>`，复用迷你版（hero 区 110×110）和大版（综合解读区 280×240）—— 通过 `showLabels` / `cx / cy / r` input 调节。

### Score Overview 环形图

SVG `<circle>` 用 `stroke-dasharray` 实现进度环：

```ts
arcDashArray = computed(() => {
  const filled = (job().total / 100) * CIRCUMFERENCE;
  return `${filled} ${CIRCUMFERENCE - filled}`;
});
```

紫色渐变通过 `<linearGradient id="scoreGradient">` 定义，`stroke="url(#scoreGradient)"` 引用。

### SubmitProgress SSE

`ApiService.streamProgress(taskId)` 返回 `Observable<AnalyzeProgressEvent>`。当前主流程是在 Dashboard 的 URL 输入提交成功后打开 `AnalyzeProgressDialogComponent` 弹窗，在弹窗中订阅 SSE：

- `events` signal 追加事件
- `currentEvent` / `percent` signal 驱动弹窗 UI
- `waiting_login` 阶段高亮橙色提示，保持 SSE 连接等待用户在 Chrome 完成登录
- 命中 `'done'` 事件时关闭弹窗，600ms 后跳转 `/results/:slug`
- 命中 `'error'` 事件时展示错误并允许用户关闭弹窗

`/jobs/:taskId` 的 `SubmitProgressComponent` 仍保留为独立进度页入口，行为与弹窗一致：

- `events` signal 追加事件
- `currentStage` / `percent` signal 驱动 UI
- 命中 `'done'` 事件时 `setTimeout` 600ms 后跳转 `/results/:slug`
- mock 模式：内置 9 帧序列模拟整条管线（从 `launching_chrome` 到 `done`），间隔 700ms

阶段状态映射：

```ts
type StageStatus = 'pending' | 'active' | 'done' | 'error';
```

`'waiting_login'` 阶段会高亮提示「请在 Chrome 窗口完成登录」。

### Drawer 历史 / 收藏列表

- `toSignal(ApiService.listResults())` 拉列表
- 顶部 segmented control 在「分析历史」与「收藏职位」间切换
- 收藏状态由 `FavoriteJobsService` 管理，持久化到 `localStorage` 的 `jobscope:favorites`
- `activeId` 通过 `Router.url` 解析得到（避免 ActivatedRoute 在 shell 层拿不到子路由参数的问题）
- 每项是 `<a [routerLink]="['/results', job.id]" routerLinkActive="active">`，点击切换无需手写导航
- 底部「候选人画像 · 已配置」是另一条路由入口

## 7. 关键设计决策

### Mock / 真实切换

通过 `environment.useMock` 单点控制：

```ts
listResults(): Observable<JobAnalysis[]> {
  if (environment.useMock) return of(MOCK_JOBS).pipe(delay(120));
  return this.http.get<JobAnalysis[]>(`${environment.apiBase}/api/results`);
}
```

mock 模式加 80-200ms 延迟，方便验证 loading 态。后端 schema 稳定后，建议在这里加 adapter 把后端响应映射成前端类型，组件代码 0 改动。

### Signal-first

全部组件用 Signals + `toSignal` + `computed`，不用 RxJS Subscribe 手动订阅：

- 路由参数：`toSignal(route.paramMap)`
- 数据：`toSignal(apiService.getX())`
- 派生状态：`computed(() => ...)`
- 局部状态：`signal(initialValue)`

好处：模板里直接 `{{ job() }}` 调用，自动跟踪依赖，无内存泄漏风险。

### 视觉风格 token 化

所有颜色、字体、间距通过 CSS 变量在 `styles.scss` 集中定义：

```scss
:root {
  --brand: #7132f5;
  --brand-dark: #5741d8;
  --green: #149e61;
  --orange: #d97757;
  --font-display: "Inter", ...;
  --font-mono: "JetBrains Mono", ...;
  // ...
}
```

组件 scope 化 SCSS 里直接用 `var(--brand)` 等，不写 hex 值。这样后续主题调整只改一处。

### 严格的英文 key 规则

接口数据 JSON 中**禁止**任何中文键名 —— 中文只能作为字符串值（用户可见文案）出现。这条规则被写入 `AGENTS.md` 并通过 TypeScript 字面量联合类型强制约束：

- `DimensionId = 'responsibility' | 'requirements' | ...`
- `CompanyScoreId = 'financialStability' | 'growth' | ...`

显示时的中文 label 从 `DIMENSIONS` / `COMPANY_SCORE_DIMENSIONS` 元数组按 id 查找。

## 8. 构建 & 启动

```bash
cd frontend
npm install               # 首次
npx ng serve              # 开发：http://127.0.0.1:4200，含 HMR
npx ng build              # 生产：dist/frontend/
npx ng build --configuration development  # 开发模式带 source map
```

最近一次构建产物体积（dev 模式）：

| Chunk | 大小 | 内容 |
| --- | --- | --- |
| `main.js` | 174 kB | 入口 + shell + drawer |
| `chunk-*.js` (initial) | 1.20 MB + 246 kB | Material + Angular runtime |
| `styles.css` | 98 kB | 主题 + 全局样式 |
| `dashboard-component.chunk` | 365 kB | 主页全部子组件 |
| `submit-progress.chunk` | 18 kB | 进度页 |
| `candidate-profile.chunk` | 688 kB | 候选人画像（含 Material Form / Expansion / Chips） |

生产构建后会进一步压缩 + tree-shake，体积约能砍掉 60-70%。

## 9. 已完成 vs 待办

✅ **完成**

- 完整项目骨架与 4 条路由
- Material 主题集成（紫色品牌色）
- 全部主页区块（hero / job-card / score-overview / analysis-tabs / company-modal）
- 共享雷达图组件
- SSE 进度页 + mock 流
- 候选人画像基本信息 / 技能 / 职业目标三个 panel
- mock 数据全套（3 职位 + 3 公司）
- API service 完整契约（含 SSE）
- 构建 + 启动验证通过

⏳ **待办**

- **后端对接**：等 FastAPI（`web/app.py`）实装后切 `useMock: false`，必要时在 `ApiService` 加 adapter 层映射后端响应
- **候选人画像**：「约束」「偏好」两个 panel 还是占位文案，需要补完整表单（建议 reactive form + `mat-chip-grid`）
- **`/results` 独立列表页**（可选）：如果想要表格/筛选/搜索式的全量列表，drawer 之外再做一个
- **导出格式升级**：当前「导出」会下载 Markdown 报告；后续可升级 PDF 导出
- **空状态 + 错误状态**：网络失败、详情不存在等需要更友好的提示
- **`dev.py`**：同时启动 FastAPI + ng serve 的本地脚本
- **E2E 测试**：当前只有构建验证，没有 Playwright / Cypress 测试

## 10. 关键文件速查

| 想做什么 | 看哪个文件 |
| --- | --- |
| 改主题色 / 字体 / 间距 | `frontend/src/styles.scss` :root 块 |
| 加新 API endpoint | `frontend/src/app/core/services/api.service.ts` |
| 改数据类型 | `frontend/src/app/core/models/job.model.ts` |
| 改 mock 数据 | `frontend/src/app/core/mock/jobs.mock.ts` |
| 加新路由页面 | `frontend/src/app/app.routes.ts` + 新建 `features/<name>/` |
| 改 drawer 行为 | `frontend/src/app/layout/drawer/` |
| 改雷达图 | `frontend/src/app/shared/radar-chart/` |
| 改主页布局 | `frontend/src/app/features/dashboard/dashboard.component.html` |
| 改单个维度详情 | `frontend/src/app/features/dashboard/analysis-tabs/` |
| 切 mock / 真实 API | `frontend/src/environments/environment.ts` |
| 后端契约 | 根目录 `AGENTS.md` |
