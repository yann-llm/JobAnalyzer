import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';

import { ApiService } from '../../core/services/api.service';
import type { AnalyzeProgressEvent } from '../../core/models/job.model';

interface StageRow {
  key: AnalyzeProgressEvent['stage'];
  label: string;
}

const STAGES: StageRow[] = [
  { key: 'launching_chrome', label: '启动 Chrome 调试实例' },
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

  readonly taskId = signal<string>('');
  readonly events = signal<AnalyzeProgressEvent[]>([]);
  readonly currentStage = signal<AnalyzeProgressEvent['stage'] | null>(null);
  readonly percent = signal<number>(0);
  readonly errorMessage = signal<string | null>(null);

  readonly stages = STAGES;

  readonly stageState = computed(() => {
    const cur = this.currentStage();
    const reached = new Set<AnalyzeProgressEvent['stage']>(this.events().map((e) => e.stage));
    return STAGES.map((s) => ({
      ...s,
      status: this.statusOf(s.key, cur, reached),
    }));
  });

  private statusOf(
    key: AnalyzeProgressEvent['stage'],
    current: AnalyzeProgressEvent['stage'] | null,
    reached: Set<AnalyzeProgressEvent['stage']>,
  ): 'pending' | 'active' | 'done' | 'error' {
    if (current === 'error') return key === current ? 'error' : 'pending';
    if (key === current) return 'active';
    if (reached.has(key) && current && this.orderOf(key) < this.orderOf(current)) return 'done';
    if (current === 'done') return 'done';
    return 'pending';
  }

  private orderOf(k: AnalyzeProgressEvent['stage']): number {
    return STAGES.findIndex((s) => s.key === k);
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('taskId') ?? '';
    this.taskId.set(id);
    if (!id) return;
    this.api.streamProgress(id).subscribe({
      next: (ev) => {
        this.events.update((prev) => [...prev, ev]);
        this.currentStage.set(ev.stage);
        if (typeof ev.percent === 'number') this.percent.set(ev.percent);
        if (ev.stage === 'done' && ev.slug) {
          setTimeout(() => this.router.navigate(['/results', ev.slug!]), 600);
        }
        if (ev.stage === 'error') {
          this.errorMessage.set(ev.message);
        }
      },
      error: (err) => this.errorMessage.set(String(err?.message ?? err)),
    });
  }
}
