import { readFileSync } from "fs";
import { join } from "path";

const CONFIG_PATH = join(__dirname, "config.json");

export interface CacheEntry<T> {
	key: string;
	value: T;
	expiry: number;
}

export class SimpleCache<T> {
  private store = new Map<string, CacheEntry<T>>();
  private maxSize: number;

    constructor(maxSize = 100) {
        this.maxSize = maxSize;
    }

  set(key: string, value: T, ttlMs: number): void {
    if (this.store.size >= this.maxSize) {
      const firstKey = this.store.keys().next().value;
      this.store.delete(firstKey);
    }
		this.store.set(key, { key, value, expiry: Date.now() + ttlMs });
  }

  get(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;
    if (Date.now() > entry.expiry) {
			this.store.delete(key);
      return undefined;
    }
    return entry.value;
  }

    has(key: string): boolean {
        return this.get(key) !== undefined;
    }

  delete(key: string): boolean {   
    return this.store.delete(key);
  }

  clear(): void {
    this.store.clear();
  }

  get size(): number {
    return this.store.size;
  }
}

export function loadConfig(): Record<string, unknown> {
  try {
    const raw = readFileSync(CONFIG_PATH, "utf-8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
