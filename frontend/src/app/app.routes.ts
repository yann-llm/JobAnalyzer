import { Routes } from '@angular/router';

import { AppShellComponent } from './layout/app-shell/app-shell.component';

export const routes: Routes = [
  {
    path: '',
    component: AppShellComponent,
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'results/:id',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'jobs/:taskId',
        loadComponent: () =>
          import('./features/submit-progress/submit-progress.component').then(
            (m) => m.SubmitProgressComponent
          ),
      },
      {
        path: 'profile',
        loadComponent: () =>
          import('./features/candidate-profile/candidate-profile.component').then(
            (m) => m.CandidateProfileComponent
          ),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
