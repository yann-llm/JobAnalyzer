import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { toSignal } from '@angular/core/rxjs-interop';

import { ApiService } from '../../../core/services/api.service';
import { scoreClass } from '../../../shared/score-utils';
import { COMPANY_SCORE_DIMENSIONS } from '../../../core/models/job.model';
import type { CompanyScoreId, CompanyScores } from '../../../core/models/job.model';

interface CompanyModalData {
  companyId: string;
}

/**
 * 公司详情 modal —— 基础信息、多维评分、简介、行业评价。
 * 对应 [index.html](../../../../../../index.html) 的 .modal-overlay。
 */
@Component({
  selector: 'jb-company-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './company-modal.component.html',
  styleUrl: './company-modal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CompanyModalComponent {
  private api = inject(ApiService);
  private dialogRef = inject(MatDialogRef<CompanyModalComponent>);
  data = inject<CompanyModalData>(MAT_DIALOG_DATA);

  readonly company = toSignal(this.api.getCompany(this.data.companyId), { initialValue: null });

  scoreClass = scoreClass;

  /**
   * 把 scores 转成 [中文名, 分数] 顺序数组。
   * 顺序按 COMPANY_SCORE_DIMENSIONS（前端固定语序），key 缺失时跳过。
   */
  scoreEntries(scores: CompanyScores): { name: string; val: number }[] {
    return COMPANY_SCORE_DIMENSIONS
      .filter((d) => typeof scores[d.id] === 'number')
      .map((d) => ({ name: d.name, val: scores[d.id] }));
  }

  close(): void {
    this.dialogRef.close();
  }
}
