/**
 * JobScope 前端核心类型。
 *
 * 数据形态对齐 [index.html](../../../../index.html) 里的 JOBS / COMPANIES 静态数据，
 * 等后端 schema 落地后，统一在 ApiService 里写映射层把后端响应转成这套类型。
 */

/** 六维评分键 —— 与雷达图、维度卡片、子 tab 一一对应 */
export type DimensionId = 'd0' | 'd1' | 'd2' | 'd3' | 'd4' | 'd5';

export interface DimensionMeta {
  id: DimensionId;
  /** 中文长名（用于卡片标题、雷达图 legend） */
  name: string;
  /** 中文短名（用于雷达图描点标签） */
  short: string;
}

export const DIMENSIONS: readonly DimensionMeta[] = [
  { id: 'd0', name: '职责质量',   short: '职责' },
  { id: 'd1', name: '要求合理性', short: '要求' },
  { id: 'd2', name: '薪酬福利',   short: '薪酬' },
  { id: 'd3', name: '工作强度',   short: '强度' },
  { id: 'd4', name: '公司评分',   short: '公司' },
  { id: 'd5', name: '行业评分',   short: '行业' },
];

/** 综合解读区的「优劣势对比」 */
export interface ProsCons {
  pros: string[];
  cons: string[];
}

/** 维度详情面板的 KPI 卡片项 */
export interface DimensionKpi {
  label: string;
  val: string;
  sub: string;
}

/** 单个维度的详细分析 */
export interface DimensionDetail {
  title: string;
  text: string;
  kpis: DimensionKpi[];
}

/** 单个职位 meta 信息（顶部图标条） */
export interface JobMetaItem {
  ico: 'location' | 'salary' | 'exp' | 'edu' | 'type' | 'team';
  label: string;
  isSalary?: boolean;
}

/** 综合解读区的「基本信息」键值对 */
export interface JobSummaryMeta {
  type: string;
  industry: string;
  edu: string;
  exp: string;
  headcount: string;
  posted: string;
}

/** 迷你雷达卡片上的徽标颜色类 */
export type MiniTagClass = 'badge-green' | 'badge-orange' | 'badge-neutral';

export interface MiniTag {
  text: string;
  cls: MiniTagClass;
}

/** 单条职位分析记录 —— 一条记录对应 data/<slug>/ 一个目录 */
export interface JobAnalysis {
  id: string;
  title: string;
  code: string;
  level: string;
  matchTag: string;
  /** 关联到 Company.id */
  company: string;
  meta: JobMetaItem[];
  summaryMeta: JobSummaryMeta;
  scores: Record<DimensionId, number>;
  total: number;
  grade: string;
  miniLabel: string;
  miniTag: MiniTag;
  summary: string[];
  pros: string[];
  cons: string[];
  details: Record<DimensionId, DimensionDetail>;
}

/** 公司多维评分（modal 里展示） */
export type CompanyScores = Record<string, number>;

export interface CompanyMeta {
  size: string;
  stage: string;
  founded: string;
  location: string;
}

export interface IndustryMetric {
  val: string;
  label: string;
}

export interface IndustryInfo {
  name: string;
  score: number;
  desc: string;
  metrics: IndustryMetric[];
}

/** 公司完整画像 —— modal 里展示 */
export interface Company {
  name: string;
  code: string;
  tags: string[];
  meta: CompanyMeta;
  /** [key, val] tuples，按显示顺序排列 */
  info: [string, string][];
  scores: CompanyScores;
  desc: string;
  industry: IndustryInfo;
}

/** 分析任务进度事件（SSE 推送） */
export interface AnalyzeProgressEvent {
  stage:
    | 'launching_chrome'
    | 'waiting_login'
    | 'scraping_job'
    | 'scraping_company'
    | 'qcc_enrich'
    | 'analyzing'
    | 'done'
    | 'error';
  message: string;
  detail?: string;
  /** 0-100 */
  percent?: number;
  /** done 时携带的目标 slug，前端跳转用 */
  slug?: string;
}
