import { Injectable, computed, signal } from '@angular/core';

const STORAGE_KEY = 'jobscope:favorites';

@Injectable({ providedIn: 'root' })
export class FavoriteJobsService {
  private readonly favoriteIdsValue = signal<Set<string>>(this.readFavorites());

  readonly favoriteIds = computed(() => this.favoriteIdsValue());
  readonly count = computed(() => this.favoriteIdsValue().size);

  isFavorite(id: string): boolean {
    return this.favoriteIdsValue().has(id);
  }

  toggle(id: string): void {
    const next = new Set(this.favoriteIdsValue());
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.favoriteIdsValue.set(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
  }

  prune(validIds: Iterable<string>): void {
    const valid = new Set(validIds);
    const next = new Set([...this.favoriteIdsValue()].filter((id) => valid.has(id)));
    if (next.size === this.favoriteIdsValue().size) return;
    this.favoriteIdsValue.set(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
  }

  private readFavorites(): Set<string> {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const values = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(values) ? values.filter((item) => typeof item === 'string') : []);
    } catch {
      return new Set();
    }
  }
}
