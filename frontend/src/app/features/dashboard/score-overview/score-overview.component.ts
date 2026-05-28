import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';

import { DIMENSIONS } from '../../../core/models/job.model';
import type { DimensionId, JobAnalysis } from '../../../core/models/job.model';
import { scoreClass } from '../../../shared/score-utils';

/**
 * 综合评分总览：左侧大环形图，右侧 3×2 维度卡片。
 * 对应 [index.html](../../../../../../index.html) 的 .score-overview。
 */
@Component({
  selector: 'jb-score-overview',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './score-overview.component.html',
  styleUrl: './score-overview.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScoreOverviewComponent {
  readonly job = input.required<JobAnalysis>();
  readonly activeDimension = input<DimensionId | null>(null);
  readonly selectDimension = output<DimensionId>();

  readonly RADIUS = 86;
  readonly CIRCUMFERENCE = 2 * Math.PI * this.RADIUS;

  readonly arcDashArray = computed(() => {
    const filled = (this.job().total / 100) * this.CIRCUMFERENCE;
    return `${filled} ${this.CIRCUMFERENCE - filled}`;
  });

  readonly dimensions = DIMENSIONS;
  scoreClass = scoreClass;

  onSelectDimension(id: DimensionId): void {
    this.selectDimension.emit(id);
  }
}
