/**
 * 评分 → 颜色类名 / 等级标签的映射。
 * 与 index.html 里 scoreClass() 完全一致，所有组件共用。
 */

export interface ScoreClass {
  color: 'score-excellent' | 'score-good' | 'score-fair' | 'score-poor';
  bar: 'bar-excellent' | 'bar-good' | 'bar-fair' | 'bar-poor';
  grade: string;
}

export function scoreClass(s: number): ScoreClass {
  if (s >= 85) return { color: 'score-excellent', bar: 'bar-excellent', grade: 'A+ 优秀' };
  if (s >= 75) return { color: 'score-good',      bar: 'bar-good',      grade: 'A 良好' };
  if (s >= 60) return { color: 'score-fair',      bar: 'bar-fair',      grade: 'B 中等' };
  return         { color: 'score-poor',      bar: 'bar-poor',      grade: 'C 较弱' };
}

/** score-class → 实际 CSS 颜色变量，用于内联 style 场景（badge 背景等） */
export function scoreCssVar(s: number): { bg: string; fg: string } {
  if (s >= 85) return { bg: 'var(--green-bg)',  fg: 'var(--green-text)'  };
  if (s >= 75) return { bg: 'var(--brand-subtle)', fg: 'var(--brand-dark)' };
  if (s >= 60) return { bg: 'var(--orange-bg)', fg: 'var(--orange-text)' };
  return         { bg: 'var(--red-bg)',    fg: 'var(--red-text)'    };
}
