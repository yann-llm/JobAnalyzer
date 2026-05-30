import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ApiService } from '../../../core/services/api.service';
import type { AnalyzeProgressEvent } from '../../../core/models/job.model';

interface AnalyzeProgressDialogData {
  taskId: string;
}

interface StageRow {
  key: AnalyzeProgressEvent['stage'];
  label: string;
}

type StageStatus = 'pending' | 'active' | 'done' | 'error';

const STAGES: StageRow[] = [
  { key: 'waiting_login', label: '等待登录' },
  { key: 'scraping_job', label: '抓取职位' },
  { key: 'scraping_company', label: '抓取公司' },
  { key: 'qcc_enrich', label: '企查查整合' },
  { key: 'analyzing', label: 'LLM 分析' },
  { key: 'done', label: '生成报告' },
];

const DETAIL_LABELS: Record<string, string> = {
  success: '已完成',
  job_value: '职位综合价值',
  company_risk: '公司风险',
  industry_outlook: '行业前景',
  final_evaluation: '综合评估',
};

@Component({
  selector: 'jb-analyze-progress-dialog',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './analyze-progress-dialog.component.html',
  styleUrl: './analyze-progress-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalyzeProgressDialogComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);
  private dialogRef = inject(MatDialogRef<AnalyzeProgressDialogComponent>);
  private data = inject<AnalyzeProgressDialogData>(MAT_DIALOG_DATA);

  readonly taskId = this.data.taskId;
  readonly events = signal<AnalyzeProgressEvent[]>([]);
  readonly currentEvent = signal<AnalyzeProgressEvent | null>(null);
  readonly percent = signal<number>(0);
  readonly errorMessage = signal<string | null>(null);
  readonly stages = STAGES;

  readonly latestEvents = computed(() => this.events().slice(-4).reverse());

  readonly currentDetail = computed(() => {
    const detail = this.currentEvent()?.detail;
    return detail ? (DETAIL_LABELS[detail] ?? detail) : '';
  });

  readonly stageState = computed(() => {
    const current = this.currentEvent()?.stage ?? null;
    const events = this.events();
    const reached = new Set<AnalyzeProgressEvent['stage']>(events.map((event) => event.stage));
    const failedStage = current === 'error' ? this.failedStageFor(events) : null;
    const stages = STAGES.map((stage) => ({
      ...stage,
      status: this.statusOf(stage.key, current, reached, events, failedStage),
    }));
    if (current !== 'error') return stages;
    return stages.filter((stage) => reached.has(stage.key) || stage.key === failedStage);
  });

  constructor() {
    this.dialogRef.disableClose = true;
    this.api.streamProgress(this.taskId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (event) => this.handleEvent(event),
      error: (err) => {
        this.dialogRef.disableClose = false;
        this.errorMessage.set(String(err?.message ?? err ?? 'SSE 连接失败'));
        this.api.refreshResults();
      },
    });
  }

  close(): void {
    if (this.errorMessage()) {
      this.dialogRef.close();
    }
  }

  private handleEvent(event: AnalyzeProgressEvent): void {
    this.events.update((prev) => [...prev, event]);
    if (this.shouldPromoteCurrent(event)) {
      this.currentEvent.set(event);
    }
    if (typeof event.percent === 'number') {
      const nextPercent = Math.max(0, Math.min(100, event.percent));
      this.percent.set(event.stage === 'error' ? Math.min(nextPercent, 99) : Math.max(this.percent(), nextPercent));
    }
    if (event.stage === 'error') {
      this.errorMessage.set(event.message);
      this.dialogRef.disableClose = false;
      this.api.refreshResults();
      return;
    }
    if (event.stage === 'done' && event.slug) {
      this.percent.set(100);
      setTimeout(() => {
        this.dialogRef.close();
        this.router.navigate(['/results', event.slug]);
      }, 600);
    }
  }

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
    if (current === 'done') return 'done';
    if (key === current) return 'active';
    if (reached.has(key)) return 'done';
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

  private orderOf(key: AnalyzeProgressEvent['stage']): number {
    return STAGES.findIndex((stage) => stage.key === key);
  }

  private shouldPromoteCurrent(event: AnalyzeProgressEvent): boolean {
    if (this.orderOf(event.stage) < 0 && event.stage !== 'error' && event.stage !== 'done') return false;
    const current = this.currentEvent();
    if (!current || event.stage === 'error' || event.stage === 'done') return true;
    const currentOrder = this.orderOf(current.stage);
    const nextOrder = this.orderOf(event.stage);
    if (nextOrder > currentOrder) return true;
    if (nextOrder === currentOrder) return true;
    return false;
  }
}
