import { Routes } from '@angular/router';

/**
 * Every feature is lazy. That is not about bundle size at this scale; it is
 * what makes "a feature may never import another feature" structural rather
 * than a convention nobody enforces. A feature that reaches sideways stops
 * building on its own.
 */
export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: 'Make a song',
    loadComponent: () =>
      import('./features/submit/submit-page').then((m) => m.SubmitPage),
  },
  {
    path: 'runs/:id',
    title: 'Making a song',
    loadComponent: () => import('./features/run/run-page').then((m) => m.RunPage),
  },
  {
    path: 'runs',
    title: 'Earlier runs',
    loadComponent: () =>
      import('./features/history/history-page').then((m) => m.HistoryPage),
  },
  { path: '**', redirectTo: '' },
];
