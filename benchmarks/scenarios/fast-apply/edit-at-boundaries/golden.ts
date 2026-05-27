import { EventEmitter } from "events";
import { logger } from "./lib/logger";

const DEFAULT_TIMEOUT_MS = 5000;
const MAX_RETRIES = 3;

export interface RetryConfig {
  maxRetries: number;
  timeoutMs: number;
  backoffFactor: number;
}

export class TaskRunner extends EventEmitter {
  private config: RetryConfig;

  constructor(config: Partial<RetryConfig> = {}) {
    super();
    this.config = {
      maxRetries: config.maxRetries ?? MAX_RETRIES,
      timeoutMs: config.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      backoffFactor: config.backoffFactor ?? 2,
    };
  }

  async run<T>(task: () => Promise<T>): Promise<T> {
    let attempt = 0;

    while (attempt <= this.config.maxRetries) {
      try {
        const result = await Promise.race([
          task(),
          this.timeout(this.config.timeoutMs * Math.pow(this.config.backoffFactor, attempt)),
        ]);
        this.emit("success", { attempt });
        return result as T;
      } catch (err) {
        attempt++;
        if (attempt > this.config.maxRetries) {
          this.emit("failure", { attempt, err });
          throw err;
        }
        this.emit("retry", { attempt, err });
      }
    }

    throw new Error("Unreachable");
  }

  private timeout(ms: number): Promise<never> {
    return new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`Task timed out after ${ms}ms`)), ms)
    );
  }
}

export default new TaskRunner();
