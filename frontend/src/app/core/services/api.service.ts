import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, of, delay, switchMap, catchError } from 'rxjs';

import { environment } from '../../../environments/environment';
import type { Company, JobAnalysis, AnalyzeProgressEvent } from '../models/job.model';
import { MOCK_COMPANIES, MOCK_JOBS } from '../mock/jobs.mock';

/**
 * 统一接口服务。
 *
 * mock 模式下从内置静态数据返回，模拟真实网络延迟，方便组件验证 loading 态。
 * 真实模式下打到 environment.apiBase（FastAPI 8000 端口）。
 *
 * 后端 schema 稳定后，在这个 service 里加一层 adapter 把后端响应映射成
 * `JobAnalysis` / `Company`，组件代码不用动。
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private resultsRefresh$ = new BehaviorSubject<void>(undefined);

  /** 历史分析列表（drawer 用） */
  listResults(): Observable<JobAnalysis[]> {
    if (environment.useMock) {
      return of(MOCK_JOBS).pipe(delay(120));
    }
    return this.resultsRefresh$.pipe(
      switchMap(() => this.http.get<JobAnalysis[]>(`${environment.apiBase}/api/results`))
    );
  }

  /** 通知所有历史列表订阅者重新拉取结果 */
  refreshResults(): void {
    this.resultsRefresh$.next();
  }

  /** 单个分析详情 */
  getResult(id: string): Observable<JobAnalysis | null> {
    if (environment.useMock) {
      const found = MOCK_JOBS.find((j) => j.id === id) ?? null;
      return of(found).pipe(delay(120));
    }
    return this.http.get<JobAnalysis>(`${environment.apiBase}/api/results/${id}`).pipe(
      catchError(() => of(null))
    );
  }

  /** 公司画像（modal 用） */
  getCompany(companyId: string): Observable<Company | null> {
    if (environment.useMock) {
      const found = MOCK_COMPANIES[companyId] ?? null;
      return of(found).pipe(delay(80));
    }
    return this.http.get<Company>(`${environment.apiBase}/api/companies/${companyId}`);
  }

  /** 提交分析任务 → 返回 task_id */
  submitAnalysis(url: string): Observable<{ taskId: string }> {
    if (environment.useMock) {
      return of({ taskId: `mock-${Date.now()}` }).pipe(delay(200));
    }
    return this.http.post<{ taskId: string }>(`${environment.apiBase}/api/analyze`, { url });
  }

  /** 对已有结果重新运行分析 → 返回 task_id */
  reanalyzeResult(id: string, url?: string): Observable<{ taskId: string }> {
    if (environment.useMock) {
      return of({ taskId: `mock-reanalyze-${Date.now()}` }).pipe(delay(200));
    }
    const body = url ? { url } : {};
    return this.http.post<{ taskId: string }>(
      `${environment.apiBase}/api/results/${id}/reanalyze`,
      body
    );
  }

  /**
   * SSE 流：订阅任务进度。
   *
   * mock 模式下用一个生成的事件序列模拟，便于前端进度页开发。
   * 真实模式下使用 EventSource 连后端 /api/analyze/{taskId}/stream。
   */
  streamProgress(taskId: string): Observable<AnalyzeProgressEvent> {
    if (environment.useMock) {
      return this.mockProgressStream();
    }
    return new Observable<AnalyzeProgressEvent>((subscriber) => {
      const url = `${environment.apiBase}/api/analyze/${taskId}/stream`;
      const es = new EventSource(url);
      let terminalEventReceived = false;
      es.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data) as AnalyzeProgressEvent;
          subscriber.next(event);
          if (event.stage === 'error') {
            terminalEventReceived = true;
            this.refreshResults();
            subscriber.complete();
            es.close();
          }
        } catch {
          // 忽略坏帧
        }
      };
      es.onerror = () => {
        if (terminalEventReceived || subscriber.closed) return;
        subscriber.error(new Error('SSE 连接中断，请稍后重试'));
      };
      es.addEventListener('done', (ev) => {
        try {
          terminalEventReceived = true;
          subscriber.next(JSON.parse((ev as MessageEvent).data) as AnalyzeProgressEvent);
          this.refreshResults();
        } catch {
          // 完成帧格式异常时仍关闭连接，避免页面卡住。
        }
        subscriber.complete();
        es.close();
      });
      return () => es.close();
    });
  }

  /** 读取候选人画像 */
  getCandidateProfile(): Observable<unknown | null> {
    if (environment.useMock) {
      return of(null).pipe(delay(80));
    }
    return this.http.get<unknown>(`${environment.apiBase}/api/candidate-profile`);
  }

  /** 写入候选人画像 */
  updateCandidateProfile(profile: unknown): Observable<{ ok: boolean }> {
    if (environment.useMock) {
      return of({ ok: true }).pipe(delay(120));
    }
    return this.http.put<{ ok: boolean }>(
      `${environment.apiBase}/api/candidate-profile`,
      profile
    );
  }

  private mockProgressStream(): Observable<AnalyzeProgressEvent> {
    const sequence: AnalyzeProgressEvent[] = [
      { stage: 'launching_chrome', message: '启动 Chrome 调试实例...', percent: 5 },
      { stage: 'scraping_job', message: '抓取职位页面正文', percent: 25 },
      { stage: 'scraping_company', message: '抓取公司详情页', percent: 45 },
      { stage: 'qcc_enrich', message: '企查查公司信息整合', percent: 60 },
      { stage: 'analyzing', message: 'LLM 分析：职位综合价值', detail: 'job_value', percent: 70 },
      { stage: 'analyzing', message: 'LLM 分析：公司风险', detail: 'company_risk', percent: 80 },
      { stage: 'analyzing', message: 'LLM 分析：行业前景', detail: 'industry_outlook', percent: 88 },
      { stage: 'analyzing', message: 'LLM 分析：综合评估', detail: 'final_evaluation', percent: 95 },
      { stage: 'done', message: '分析完成', percent: 100, slug: 'job-1' },
    ];
    return new Observable<AnalyzeProgressEvent>((subscriber) => {
      let i = 0;
      const tick = () => {
        if (i >= sequence.length) {
          subscriber.complete();
          return;
        }
        subscriber.next(sequence[i++]);
        timer = setTimeout(tick, 700);
      };
      let timer = setTimeout(tick, 300);
      return () => clearTimeout(timer);
    });
  }
}
