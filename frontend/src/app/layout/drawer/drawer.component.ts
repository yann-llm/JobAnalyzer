import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';

import { ApiService } from '../../core/services/api.service';
import { scoreClass } from '../../shared/score-utils';
import type { JobAnalysis } from '../../core/models/job.model';

/**
 * 侧边栏 —— 分析历史列表 + 品牌头 + 状态条。
 * 对应 [index.html](../../../../../index.html) 里的 .drawer。
 */
@Component({
  selector: 'jb-drawer',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './drawer.component.html',
  styleUrl: './drawer.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DrawerComponent {
  private api = inject(ApiService);
  private router = inject(Router);

  readonly jobs = toSignal(this.api.listResults(), { initialValue: [] as JobAnalysis[] });
  readonly count = computed(() => this.jobs().length);

  /** 当前选中职位 id（从 URL 解析）。空就高亮第一个。 */
  readonly activeId = computed(() => {
    const list = this.jobs();
    if (!list.length) return null;
    const segments = this.router.url.split('/').filter(Boolean);
    if (segments[0] === 'results' && segments[1]) return segments[1];
    return list[0].id;
  });

  scoreClass = scoreClass;

  /** 抓 meta 数组里第一个 location 类型 item 的城市部分 */
  firstLocation(job: JobAnalysis): string {
    const loc = job.meta.find((m) => m.ico === 'location');
    return loc?.label.split(' · ')[0] ?? '';
  }
}
