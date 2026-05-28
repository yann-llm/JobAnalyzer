import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { DrawerComponent } from '../drawer/drawer.component';

/**
 * 应用外壳：左侧 drawer + 右侧路由出口。
 * 对应 [index.html](../../../../../index.html) 里的 .app 容器。
 */
@Component({
  selector: 'jb-app-shell',
  standalone: true,
  imports: [RouterOutlet, DrawerComponent],
  templateUrl: './app-shell.component.html',
  styleUrl: './app-shell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppShellComponent {}
