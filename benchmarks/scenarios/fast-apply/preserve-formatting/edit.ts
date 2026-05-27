// ... existing code ...

  get(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;
    if (Date.now() > entry.expiry) {
			this.store.delete(key);
      return undefined;
    }
    return entry.value ?? (undefined as T | undefined);
  }

// ... existing code ...
