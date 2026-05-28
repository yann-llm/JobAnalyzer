import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
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
import type { DimensionId, JobAnalysis } from '../../core/models/job.model';

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

  selectDimensionTab(id: DimensionId): void {
    this.activeAnalysisTab.set(id);
  }
}
