import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService } from '../../../core/services/api.service';
import { RadarChartComponent } from '../../../shared/radar-chart/radar-chart.component';
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
  private router = inject(Router);

  readonly job = input.required<JobAnalysis>();
  readonly urlInput = signal<string>('');
  readonly submitting = signal<boolean>(false);

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

  submit(): void {
    const url = this.urlInput().trim();
    if (!url || this.submitting()) return;
    this.submitting.set(true);
    this.api.submitAnalysis(url).subscribe({
      next: (res) => {
        this.submitting.set(false);
        this.router.navigate(['/jobs', res.taskId]);
      },
      error: () => this.submitting.set(false),
    });
  }
}
