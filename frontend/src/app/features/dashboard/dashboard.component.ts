import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { switchMap } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import { CompanyModalComponent } from './company-modal/company-modal.component';
import { HeroSearchComponent } from './hero-search/hero-search.component';
import { JobCardComponent } from './job-card/job-card.component';
import { ScoreOverviewComponent } from './score-overview/score-overview.component';
import { AnalysisTabsComponent } from './analysis-tabs/analysis-tabs.component';
import type { JobAnalysis } from '../../core/models/job.model';

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

  /** URL 里的 :id（无则取历史中第一个） */
  private routeId = toSignal(this.route.paramMap, { initialValue: null });
  private allJobs = toSignal(this.api.listResults(), { initialValue: [] as JobAnalysis[] });

  readonly activeJobId = computed(() => {
    const fromRoute = this.routeId()?.get('id');
    if (fromRoute) return fromRoute;
    return this.allJobs()[0]?.id ?? null;
  });

  /** 详情数据 —— 根据 activeJobId 拉取 */
  readonly job = toSignal(
    this.route.paramMap.pipe(
      switchMap((p) => {
        const id = p.get('id') ?? '__first__';
        return this.api.getResult(id === '__first__' ? '' : id);
      })
    ),
    { initialValue: null as JobAnalysis | null }
  );

  /** 拉不到（如初次进首页）就回落到列表里的第一条 */
  readonly displayJob = computed(() => this.job() ?? this.allJobs()[0] ?? null);

  readonly analysisTime = computed(() => {
    // 后端没出时间字段前，先用一个固定的展示值
    return '2024-12-18 14:32';
  });

  openCompany(companyId: string): void {
    this.dialog.open(CompanyModalComponent, {
      data: { companyId },
      panelClass: 'jb-company-modal',
      maxWidth: '720px',
      width: '100%',
    });
  }
}
