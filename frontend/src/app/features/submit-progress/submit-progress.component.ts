import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ApiService } from '../../core/services/api.service';
import type { AnalyzeProgressEvent } from '../../core/models/job.model';

interface StageRow {
  key: AnalyzeProgressEvent['stage'];
  label: string;
}

type StageStatus = 'pending' | 'active' | 'done' | 'error';

const STAGES: StageRow[] = [
  { key: 'waiting_login',    label: '等待用户登录（如触发）' },
  { key: 'scraping_job',     label: '抓取职位页面正文' },
  { key: 'scraping_company', label: '抓取公司详情页' },
  { key: 'qcc_enrich',       label: '企查查公司信息整合' },
  { key: 'analyzing',        label: 'LLM 分析（4 个子模块）' },
  { key: 'done',             label: '生成报告' },
];

/**
 * SSE 进度页 —— 用户提交 URL 后跳转到这里，订阅后端的分析进度推送。
 * 完成时跳转回 /results/:id。
 */
@Component({
  selector: 'jb-submit-progress',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './submit-progress.component.html',
  styleUrl: './submit-progress.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SubmitProgressComponent {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);

  readonly taskId = signal<string>('');
  readonly events = signal<AnalyzeProgressEvent[]>([]);
  readonly currentStage = signal<AnalyzeProgressEvent['stage'] | null>(null);
  readonly percent = signal<number>(0);
  readonly errorMessage = signal<string | null>(null);

  readonly stages = STAGES;

  readonly stageState = computed(() => {
    const cur = this.currentStage();
    const events = this.events();
    const reached = new Set<AnalyzeProgressEvent['stage']>(events.map((e) => e.stage));
    const failedStage = cur === 'error' ? this.failedStageFor(events) : null;
    const stages = STAGES.map((s) => ({
      ...s,
      status: this.statusOf(s.key, cur, reached, events, failedStage),
    }));
    if (cur !== 'error') return stages;
    return stages.filter((stage) => reached.has(stage.key) || stage.key === failedStage);
  });

  private statusOf(
    key: AnalyzeProgressEvent['stage'],
    current: AnalyzeProgressEvent['stage'] | null,
    reached: Set<AnalyzeProgressEvent['stage']>,
    events: AnalyzeProgressEvent[],
    failedStage: AnalyzeProgressEvent['stage'] | null,
  ): StageStatus {
    if (current === 'error') {
      if (key === failedStage) return 'error';
      if (key === 'waiting_login') return this.loginSucceeded(events) ? 'done' : 'pending';
      if (key === 'scraping_company') return this.companyScrapeSucceeded(events) ? 'done' : 'pending';
      if (failedStage && reached.has(key) && this.orderOf(key) < this.orderOf(failedStage)) return 'done';
      return 'pending';
    }
    if (key === 'waiting_login') {
      if (this.loginSucceeded(events)) return 'done';
      if (current === 'waiting_login') return 'active';
      return reached.has(key) ? 'done' : 'pending';
    }
    if (key === 'scraping_company') {
      if (this.companyScrapeSucceeded(events)) return 'done';
      if (current === 'scraping_company') return 'active';
      return 'pending';
    }
    if (key === current) return 'active';
    if (reached.has(key) && current && this.orderOf(key) < this.orderOf(current)) return 'done';
    if (current === 'done') return 'done';
    return 'pending';
  }

  private failedStageFor(events: AnalyzeProgressEvent[]): AnalyzeProgressEvent['stage'] | null {
    const error = [...events].reverse().find((event) => event.stage === 'error');
    const detail = error?.detail ?? '';
    const message = error?.message ?? '';
    if (this.isUsccFailure(detail, message)) return 'scraping_company';
    if (detail === 'company_info_failed' || detail === 'company_info_error') return 'qcc_enrich';
    if (detail === 'analysis_failed' || detail === 'analysis_missing') return 'analyzing';
    const previous = [...events].reverse().find((event) => event.stage !== 'error');
    return previous?.stage ?? null;
  }

  private isUsccFailure(detail: string, message: string): boolean {
    return (
      detail === 'company_uscc_unresolved' ||
      message.includes('统一社会信用代码') ||
      message.toUpperCase().includes('USCC')
    );
  }

  private companyScrapeSucceeded(events: AnalyzeProgressEvent[]): boolean {
    return events.some((event) => event.stage === 'scraping_company' && event.detail === 'success');
  }

  private loginSucceeded(events: AnalyzeProgressEvent[]): boolean {
    return events.some((event) => event.stage === 'waiting_login' && event.detail === 'success');
  }

  private orderOf(k: AnalyzeProgressEvent['stage']): number {
    return STAGES.findIndex((s) => s.key === k);
  }

  private shouldPromoteCurrent(event: AnalyzeProgressEvent): boolean {
    if (this.orderOf(event.stage) < 0 && event.stage !== 'error' && event.stage !== 'done') return false;
    const current = this.currentStage();
    if (!current || event.stage === 'error' || event.stage === 'done') return true;
    const currentOrder = this.orderOf(current);
    const nextOrder = this.orderOf(event.stage);
    if (nextOrder > currentOrder) return true;
    if (nextOrder === currentOrder) return true;
    return false;
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('taskId') ?? '';
    this.taskId.set(id);
    if (!id) return;
    this.api.streamProgress(id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (ev) => {
        this.events.update((prev) => [...prev, ev]);
        if (this.shouldPromoteCurrent(ev)) {
          this.currentStage.set(ev.stage);
        }
        if (typeof ev.percent === 'number') {
          this.percent.set(ev.stage === 'error' ? Math.min(ev.percent, 99) : Math.max(this.percent(), ev.percent));
        }
        if (ev.stage === 'done' && ev.slug) {
          setTimeout(() => this.router.navigate(['/results', ev.slug!]), 600);
        }
        if (ev.stage === 'error') {
          this.errorMessage.set(ev.message);
          this.api.refreshResults();
        }
      },
      error: (err) => {
        this.errorMessage.set(String(err?.message ?? err));
        this.api.refreshResults();
      },
    });
  }
}
