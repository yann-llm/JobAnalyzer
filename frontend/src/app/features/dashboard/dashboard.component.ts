import { ChangeDetectionStrategy, Component, computed, inject, signal, viewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { combineLatest, map, of, shareReplay, switchMap } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import { CompanyModalComponent } from './company-modal/company-modal.component';
import { HeroSearchComponent } from './hero-search/hero-search.component';
import { JobCardComponent } from './job-card/job-card.component';
import { ScoreOverviewComponent } from './score-overview/score-overview.component';
import { AnalysisTabsComponent } from './analysis-tabs/analysis-tabs.component';
import { DIMENSIONS, type DimensionId, type JobAnalysis } from '../../core/models/job.model';

type AnalysisTabKey = 'summary' | DimensionId;

/**
 * 主页面 = Hero 搜索条 + 当前选中职位的完整分析报告。
 *
 * 路由 `/` 或 `/results/:id` 共用本组件；URL 里没指定时默认展示历史中第一条。
 * 对应 [index.html](../../../../../index.html) 的 .main 容器内全部内容。
 */
@Component({
  selector: 'jb-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    HeroSearchComponent,
    JobCardComponent,
    ScoreOverviewComponent,
    AnalysisTabsComponent,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
  private dialog = inject(MatDialog);
  private heroSearch = viewChild(HeroSearchComponent);
  private allJobs$ = this.api.listResults().pipe(
    shareReplay({ bufferSize: 1, refCount: true })
  );

  /** URL 里的 :id（无则取历史中第一个） */
  private routeId = toSignal(this.route.paramMap, { initialValue: null });
  private allJobs = toSignal(this.allJobs$, { initialValue: [] as JobAnalysis[] });
  readonly activeAnalysisTab = signal<AnalysisTabKey>('summary');
  readonly activeDimension = computed<DimensionId | null>(() => {
    const tab = this.activeAnalysisTab();
    return tab === 'summary' ? null : tab;
  });

  readonly activeJobId = computed(() => {
    const fromRoute = this.routeId()?.get('id');
    if (fromRoute) return fromRoute;
    return this.allJobs()[0]?.id ?? null;
  });

  /** 详情数据 —— 根据 activeJobId 拉取 */
  readonly job = toSignal(
    combineLatest([
      this.route.paramMap.pipe(map((p) => p.get('id'))),
      this.allJobs$,
    ]).pipe(
      switchMap(([routeId, jobs]) => {
        const id = routeId ?? jobs[0]?.id ?? null;
        return id ? this.api.getResult(id) : of(null);
      })
    ),
    { initialValue: null as JobAnalysis | null }
  );

  /** 只渲染完整详情，避免列表接口裁剪 details 后把不完整数据传给详情区块。 */
  readonly displayJob = computed(() => this.job());

  readonly analysisTime = computed(() => {
    return this.displayJob()?.generatedAt ?? '';
  });

  openCompany(companyId: string): void {
    this.dialog.open(CompanyModalComponent, {
      data: { companyId },
      panelClass: 'jb-company-modal',
      maxWidth: '720px',
      width: '100%',
    });
  }

  reanalyze(job: JobAnalysis): void {
    this.heroSearch()?.reanalyze(job.id, job.sourceUrl);
  }

  exportReport(job: JobAnalysis): void {
    const blob = new Blob([this.reportMarkdown(job)], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${this.safeFileName(job.title || job.id)}-analysis.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  selectDimensionTab(id: DimensionId): void {
    this.activeAnalysisTab.set(id);
  }

  private reportMarkdown(job: JobAnalysis): string {
    const dimensionNames = new Map(DIMENSIONS.map((dimension) => [dimension.id, dimension.name]));
    const lines = [
      `# ${job.title}`,
      '',
      `- 编号：${job.code}`,
      `- 等级：${job.level || '未提供'}`,
      `- 综合评分：${job.total}`,
      `- 建议：${job.grade}`,
      job.generatedAt ? `- 生成时间：${job.generatedAt}` : '',
      job.sourceUrl ? `- 原始链接：${job.sourceUrl}` : '',
      '',
      '## 摘要',
      ...job.summary.map((item) => `- ${item}`),
      '',
      '## 亮点',
      ...job.pros.map((item) => `- ${item}`),
      '',
      '## 风险',
      ...job.cons.map((item) => `- ${item}`),
      '',
      '## 维度评分',
      ...Object.entries(job.scores).map(([key, value]) => {
        const label = dimensionNames.get(key as DimensionId) ?? key;
        return `- ${label}: ${value}`;
      }),
      '',
      '## 维度详情',
      ...Object.entries(job.details).flatMap(([key, detail]) => [
        '',
        `### ${dimensionNames.get(key as DimensionId) ?? key} · ${detail.title}`,
        detail.text,
        '',
        ...detail.kpis.filter((kpi) => kpi.label || kpi.val).map((kpi) => `- ${kpi.label}: ${kpi.val}${kpi.sub ? ` (${kpi.sub})` : ''}`),
      ]),
      '',
    ];
    return lines.filter((line) => line !== '').join('\n') + '\n';
  }

  private safeFileName(value: string): string {
    return value.trim().replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '-').slice(0, 80) || 'job';
  }
}
