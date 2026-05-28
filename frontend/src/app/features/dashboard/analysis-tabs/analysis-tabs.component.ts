import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';

import { DIMENSIONS } from '../../../core/models/job.model';
import type { DimensionId, DimensionMeta, JobAnalysis } from '../../../core/models/job.model';
import { scoreClass, scoreCssVar } from '../../../shared/score-utils';
import { RadarChartComponent } from '../../../shared/radar-chart/radar-chart.component';

type TabKey = 'summary' | DimensionId;

/**
 * 子 tab 区：综合解读 + 6 个维度详情。
 * 对应 [index.html](../../../../../../index.html) 的 .analysis 区块。
 */
@Component({
  selector: 'jb-analysis-tabs',
  standalone: true,
  imports: [CommonModule, RadarChartComponent],
  templateUrl: './analysis-tabs.component.html',
  styleUrl: './analysis-tabs.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalysisTabsComponent {
  readonly job = input.required<JobAnalysis>();
  readonly active = signal<TabKey>('summary');

  readonly dimensions = DIMENSIONS;
  scoreClass = scoreClass;
  scoreCssVar = scoreCssVar;

  setActive(tab: TabKey): void {
    this.active.set(tab);
  }

  /** 按 id 查找维度元信息（模板里取 name / short 用） */
  dimensionById(id: DimensionId): DimensionMeta {
    return DIMENSIONS.find((d) => d.id === id)!;
  }

  /** 评估细项（criteria）—— 算法搬自 index.html，把 KPI label 投射成 0-100 条形 */
  criteriaBar(label: string, score: number) {
    const numVal = score + ((label.length % 7) * 3 - 10);
    const v = Math.min(100, Math.max(10, numVal));
    let color = 'var(--red)';
    if (v >= 80) color = 'var(--green)';
    else if (v >= 60) color = 'var(--brand)';
    else if (v >= 40) color = 'var(--orange)';
    return { v, color };
  }

  readonly radarLegend = computed(() =>
    this.dimensions.map((d) => {
      const s = this.job().scores[d.id];
      return { name: d.name, score: s, cls: scoreClass(s) };
    })
  );
}
