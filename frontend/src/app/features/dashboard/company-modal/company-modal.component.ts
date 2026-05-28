import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { toSignal } from '@angular/core/rxjs-interop';

import { ApiService } from '../../../core/services/api.service';
import { scoreClass } from '../../../shared/score-utils';
import type { CompanyScores } from '../../../core/models/job.model';

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

  /** 把 scores object 转成 entries 数组，模板里 @for 用 */
  scoreEntries(scores: CompanyScores): { key: string; val: number }[] {
    return Object.entries(scores).map(([key, val]) => ({ key, val }));
  }

  close(): void {
    this.dialogRef.close();
  }
}
