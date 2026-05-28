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

const STAGES: StageRow[] = [
  { key: 'launching_chrome', label: '启动 Chrome' },
  { key: 'waiting_login', label: '等待登录' },
  { key: 'scraping_job', label: '抓取职位' },
  { key: 'scraping_company', label: '抓取公司' },
  { key: 'qcc_enrich', label: '企查查整合' },
  { key: 'analyzing', label: 'LLM 分析' },
  { key: 'done', label: '生成报告' },
];

const DETAIL_LABELS: Record<string, string> = {
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
    const reached = new Set<AnalyzeProgressEvent['stage']>(this.events().map((event) => event.stage));
    return STAGES.map((stage) => ({
      ...stage,
      status: this.statusOf(stage.key, current, reached),
    }));
  });

  constructor() {
    this.dialogRef.disableClose = true;
    this.api.streamProgress(this.taskId).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (event) => this.handleEvent(event),
      error: (err) => {
        this.dialogRef.disableClose = false;
        this.errorMessage.set(String(err?.message ?? err ?? 'SSE 连接失败'));
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
    this.currentEvent.set(event);
    if (typeof event.percent === 'number') {
      this.percent.set(Math.max(0, Math.min(100, event.percent)));
    }
    if (event.stage === 'error') {
      this.errorMessage.set(event.message);
      this.dialogRef.disableClose = false;
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
  ): 'pending' | 'active' | 'done' | 'error' {
    if (key === current && current === 'error') return 'error';
    if (current === 'done') return 'done';
    if (key === current) return 'active';
    if (reached.has(key)) return 'done';
    return 'pending';
  }
}
