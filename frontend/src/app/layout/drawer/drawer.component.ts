import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map, startWith, tap } from 'rxjs';

import { ApiService } from '../../core/services/api.service';
import { FavoriteJobsService } from '../../core/services/favorite-jobs.service';
import { scoreClass } from '../../shared/score-utils';
import type { JobAnalysis } from '../../core/models/job.model';

type DrawerTab = 'history' | 'favorites';

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
  private favorites = inject(FavoriteJobsService);
  private router = inject(Router);
  private readonly jobsLoaded = signal(false);

  readonly jobs = toSignal(
    this.api.listResults().pipe(tap(() => this.jobsLoaded.set(true))),
    { initialValue: [] as JobAnalysis[] }
  );
  readonly activeTab = signal<DrawerTab>('history');
  private readonly currentUrl = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
      startWith(this.router.url)
    ),
    { initialValue: this.router.url }
  );
  readonly favoriteCount = computed(() => {
    const favoriteIds = this.favorites.favoriteIds();
    return this.jobs().filter((job) => favoriteIds.has(job.id)).length;
  });
  readonly visibleJobs = computed(() => {
    if (this.activeTab() === 'history') return this.jobs();
    const favoriteIds = this.favorites.favoriteIds();
    return this.jobs().filter((job) => favoriteIds.has(job.id));
  });
  readonly count = computed(() => this.visibleJobs().length);
  readonly emptyText = computed(() =>
    this.activeTab() === 'favorites' ? '还没有收藏职位' : '还没有分析记录'
  );

  constructor() {
    effect(() => {
      if (!this.jobsLoaded()) return;
      this.favorites.prune(this.jobs().map((job) => job.id));
    });
  }

  /** 当前选中职位 id（从 URL 解析）。空就高亮第一个。 */
  readonly activeId = computed(() => {
    const list = this.visibleJobs();
    if (!list.length) return null;
    const segments = this.currentUrl().split('/').filter(Boolean);
    if (segments[0] === 'results' && segments[1]) return segments[1];
    return list[0].id;
  });

  scoreClass = scoreClass;

  /** 抓 meta 数组里第一个 location 类型 item 的城市部分 */
  firstLocation(job: JobAnalysis): string {
    const loc = job.meta.find((m) => m.ico === 'location');
    return loc?.label.split(' · ')[0] ?? '';
  }

  selectTab(tab: DrawerTab): void {
    this.activeTab.set(tab);
  }
}
