import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { toSignal } from '@angular/core/rxjs-interop';
import { switchMap, of } from 'rxjs';

import { ApiService } from '../../../core/services/api.service';
import type { JobAnalysis, JobMetaItem } from '../../../core/models/job.model';

/**
 * 职位 header 卡片：标题、徽标、meta 信息、操作按钮。
 * 对应 [index.html](../../../../../../index.html) 的 .job-card。
 */
@Component({
  selector: 'jb-job-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './job-card.component.html',
  styleUrl: './job-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobCardComponent {
  private api = inject(ApiService);

  readonly job = input.required<JobAnalysis>();
  readonly openCompany = output<void>();

  /** 关联公司用于读取名称展示 */
  private company$ = toSignal(
    this.api.listResults().pipe(
      switchMap(() => {
        const j = this.job();
        return j ? this.api.getCompany(j.company) : of(null);
      })
    ),
    { initialValue: null }
  );

  readonly companyName = computed(() => this.company$()?.name ?? '');

  readonly matchBadgeClass = computed(() => 'badge ' + this.job().miniTag.cls);

  /** 内联 SVG path 字典，与 index.html metaIcon() 一一对应 */
  private static readonly ICON_PATHS: Record<JobMetaItem['ico'], string> = {
    location: 'M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 1118 0z|M12 10m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0',
    salary: 'M12 2a10 10 0 100 20 10 10 0 000-20z|M8 14s1.5 2 4 2 4-2 4-2|M12 7v6',
    exp: 'M3 4h18v18H3z|M16 2v4|M8 2v4|M3 10h18',
    edu: 'M22 10v6|M12 5l10 5-10 5L2 10l10-5z',
    type: 'M3 6h18v14H3z|M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2',
    team: 'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2|M9 7m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0|M23 21v-2a4 4 0 00-3-3.87',
  };

  iconPaths(kind: JobMetaItem['ico']): string[] {
    return JobCardComponent.ICON_PATHS[kind].split('|');
  }

  onOpenCompany(): void {
    this.openCompany.emit();
  }
}
