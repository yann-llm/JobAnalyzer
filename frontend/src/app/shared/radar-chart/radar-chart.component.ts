import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { CommonModule } from '@angular/common';

import { DIMENSIONS } from '../../core/models/job.model';
import type { DimensionId } from '../../core/models/job.model';

/**
 * 六维评分雷达图。
 *
 * 算法直接搬自 [index.html](../../../../index.html) 的 buildRadar()，
 * 用 SVG polygon + spokes 渲染，无第三方依赖。
 *
 * 使用：
 *   <jb-radar-chart [scores]="job.scores" [showLabels]="true" [cx]="140" [cy]="120" [r]="80" />
 *   迷你版（drawer 旁）：[showLabels]="false" [cx]="50" [cy]="50" [r]="32"
 */
@Component({
  selector: 'jb-radar-chart',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './radar-chart.component.html',
  styleUrl: './radar-chart.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RadarChartComponent {
  readonly scores = input.required<Record<DimensionId, number>>();
  readonly showLabels = input<boolean>(true);
  readonly cx = input<number>(140);
  readonly cy = input<number>(120);
  readonly r = input<number>(80);
  readonly viewBoxW = input<number>(280);
  readonly viewBoxH = input<number>(240);

  /** 每个维度对应的角度（从顶部 12 点开始顺时针） */
  private readonly angles = computed(() => {
    const N = DIMENSIONS.length;
    return DIMENSIONS.map((_, i) => -Math.PI / 2 + (i * 2 * Math.PI) / N);
  });

  /** 背景环 polygon 顶点（4 圈：25/50/75/100%） */
  readonly rings = computed(() => {
    const cx = this.cx();
    const cy = this.cy();
    const R = this.r();
    const angles = this.angles();
    return [0.25, 0.5, 0.75, 1].map((ratio, i) => ({
      points: angles
        .map((a) => {
          const x = cx + Math.cos(a) * R * ratio;
          const y = cy + Math.sin(a) * R * ratio;
          return `${x.toFixed(2)},${y.toFixed(2)}`;
        })
        .join(' '),
      filled: i === 3,
    }));
  });

  /** 中心向外的辐条 */
  readonly spokes = computed(() => {
    const cx = this.cx();
    const cy = this.cy();
    const R = this.r();
    return this.angles().map((a) => ({
      x2: (cx + Math.cos(a) * R).toFixed(2),
      y2: (cy + Math.sin(a) * R).toFixed(2),
    }));
  });

  /** 维度短名标签的位置 */
  readonly labels = computed(() => {
    const cx = this.cx();
    const cy = this.cy();
    const R = this.r();
    return DIMENSIONS.map((d, i) => {
      const a = this.angles()[i];
      const x = cx + Math.cos(a) * (R + 18);
      const y = cy + Math.sin(a) * (R + 18) + 4;
      let anchor: 'middle' | 'start' | 'end' = 'middle';
      if (Math.abs(Math.cos(a)) >= 0.2) {
        anchor = Math.cos(a) > 0 ? 'start' : 'end';
      }
      return { text: d.short, x: x.toFixed(2), y: y.toFixed(2), anchor };
    });
  });

  /** 数据 polygon 顶点 */
  readonly dataPoints = computed(() => {
    const cx = this.cx();
    const cy = this.cy();
    const R = this.r();
    const scores = this.scores();
    return this.angles().map((a, i) => {
      const ratio = scores[DIMENSIONS[i].id] / 100;
      return {
        x: cx + Math.cos(a) * R * ratio,
        y: cy + Math.sin(a) * R * ratio,
      };
    });
  });

  readonly dataPolygonPoints = computed(() =>
    this.dataPoints()
      .map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`)
      .join(' ')
  );
}
