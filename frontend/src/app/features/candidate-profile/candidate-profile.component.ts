import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { FormsModule } from '@angular/forms';

/**
 * 候选人画像 —— 占位版本。
 *
 * 五个 panel 对应 candidate_profile.example.json 的五大块：
 *   basic / skills / career_goals / constraints / preferences
 *
 * 当前是只读模板 + 部分输入字段。后端 GET/PUT /api/candidate-profile 通了后，
 * 改成 reactive form + 数组字段用 mat-chip-grid。
 */
@Component({
  selector: 'jb-candidate-profile',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatExpansionModule,
    MatFormFieldModule,
    MatInputModule,
    MatChipsModule,
    MatIconModule,
    MatButtonModule,
  ],
  templateUrl: './candidate-profile.component.html',
  styleUrl: './candidate-profile.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CandidateProfileComponent {
  readonly years = signal<number>(5);
  readonly currentSalary = signal<string>('25K/月 · 14薪');
  readonly currentCity = signal<string>('成都');
  readonly idealSalary = signal<string>('35K/月 · 14薪');
  readonly minSalary = signal<string>('25K/月 · 14薪');
  readonly shortGoal = signal<string>('进入 AI Agent / 大模型应用方向的核心岗位');
  readonly longGoal = signal<string>('成为 AI 应用架构师或技术合伙人');

  readonly languages = signal<string[]>(['Python', 'Go', 'TypeScript']);
  readonly frameworks = signal<string[]>(['FastAPI', 'React', 'PostgreSQL']);

  removeLanguage(name: string): void {
    this.languages.update((list) => list.filter((x) => x !== name));
  }

  addLanguage(input: HTMLInputElement): void {
    const v = input.value.trim();
    if (v) {
      this.languages.update((list) => [...list, v]);
      input.value = '';
    }
  }

  save(): void {
    // TODO: PUT /api/candidate-profile
    console.log('save profile', {
      years: this.years(),
      languages: this.languages(),
    });
  }
}
