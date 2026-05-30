import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ApiService } from '../../../core/services/api.service';
import { RadarChartComponent } from '../../../shared/radar-chart/radar-chart.component';
import { AnalyzeProgressDialogComponent } from '../analyze-progress-dialog/analyze-progress-dialog.component';
import type { JobAnalysis } from '../../../core/models/job.model';

/**
 * 顶部 Hero —— 左侧标题 + URL 输入，右侧迷你雷达卡片。
 * 对应 [index.html](../../../../../../index.html) 的 .hero 区块。
 */
@Component({
  selector: 'jb-hero-search',
  standalone: true,
  imports: [CommonModule, FormsModule, RadarChartComponent],
  templateUrl: './hero-search.component.html',
  styleUrl: './hero-search.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeroSearchComponent {
  private api = inject(ApiService);
  private dialog = inject(MatDialog);
  private destroyRef = inject(DestroyRef);

  readonly job = input.required<JobAnalysis>();
  readonly inputEl = viewChild<ElementRef<HTMLInputElement>>('urlField');
  readonly urlInput = signal<string>('');
  readonly submitting = signal<boolean>(false);
  readonly submitError = signal<string | null>(null);

  readonly tagStyle = computed(() => {
    const cls = this.job().miniTag.cls;
    if (cls === 'badge-orange') {
      return { background: 'var(--orange-bg)', color: 'var(--orange-text)' };
    }
    if (cls === 'badge-neutral') {
      return { background: 'rgba(104, 107, 130, 0.12)', color: 'var(--fg-2)' };
    }
    return { background: 'var(--green-bg)', color: 'var(--green-text)' };
  });

  constructor() {
    effect(() => {
      this.urlInput.set(this.job().sourceUrl ?? '');
    });
  }

  submit(): void {
    const url = this.urlInput().trim();
    this.submitUrl(url);
  }

  reanalyze(resultId: string, sourceUrl?: string): void {
    if (sourceUrl) {
      this.urlInput.set(sourceUrl);
    }
    this.reanalyzeResult(resultId, sourceUrl);
  }

  private submitUrl(url: string): void {
    if (!url || this.submitting()) return;
    this.submitError.set(null);
    this.submitting.set(true);
    this.api.submitAnalysis(url).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        this.submitting.set(false);
        this.openProgressDialog(res.taskId);
      },
      error: (err) => {
        this.submitting.set(false);
        this.submitError.set(String(err?.message ?? err ?? '提交失败'));
      },
    });
  }

  private reanalyzeResult(resultId: string, sourceUrl?: string): void {
    if (!resultId || this.submitting()) return;
    this.submitError.set(null);
    this.submitting.set(true);
    this.api.reanalyzeResult(resultId, sourceUrl).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => {
        this.submitting.set(false);
        this.openProgressDialog(res.taskId);
      },
      error: (err) => {
        this.submitting.set(false);
        this.submitError.set(String(err?.message ?? err ?? '重新分析失败'));
      },
    });
  }

  private openProgressDialog(taskId: string): void {
    this.dialog.open(AnalyzeProgressDialogComponent, {
      data: { taskId },
      panelClass: 'jb-analyze-progress-dialog',
      maxWidth: 'calc(100vw - 32px)',
      width: '560px',
    });
  }
}
