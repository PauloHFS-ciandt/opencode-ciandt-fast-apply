#!/usr/bin/env python3 -u
"""
OpenCode Benchmark Suite — Fast Apply + Compaction
Reproducible benchmark for CI&T proxy models.

Usage:
    python3 benchmark.py                  # full run
    python3 benchmark.py --fast-apply-only
    python3 benchmark.py --compaction-only
    python3 benchmark.py --save           # also write BENCHMARK.md
"""

import json, time, os, sys, urllib.request
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

PROXY = os.environ.get("FLOW_LITELLM_PROXY", "https://flow.ciandt.com/flow-llm-proxy")
PROXY_URL = f"{PROXY}/v1/chat/completions"
API_KEY = os.environ.get("FLOW_API_KEY", "")
TIMEOUT = 60
MARKER = "// ... existing code ..."

MODELS = [
    "anthropic.claude-4-6-opus", "anthropic.claude-4-6-sonnet",
    "anthropic.claude-4-5-sonnet", "anthropic.claude-4-5-haiku",
    "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash",
    "gpt5.5", "gpt5.2", "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-5-nano",
    "gpt-4.1", "gpt-4o-mini", "o3-mini",
    "DeepSeek-R1", "DeepSeek-V4-Pro", "mistral-small-2503",
]

# ─────────────────────────────────────────────────────────────────────────────
# HTTP helper
# ─────────────────────────────────────────────────────────────────────────────

def call(model, system, user, max_tokens=4096, timeout=TIMEOUT):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(PROXY_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
        dt = time.time() - t0
        c = d["choices"][0]["message"]["content"]
        u = d.get("usage", {})
        return {"ok": True, "content": c, "time": round(dt, 1),
                "tokens_in": u.get("prompt_tokens", 0), "tokens_out": u.get("completion_tokens", 0)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:80], "time": round(time.time() - t0, 1)}

# ─────────────────────────────────────────────────────────────────────────────
# Quality scoring
# ─────────────────────────────────────────────────────────────────────────────

def score_checks(content, must_have, must_not_have=None):
    if not content:
        return 0, len(must_have), "EMPTY"
    low = content.lower()
    passed = sum(1 for group in must_have if any(kw.lower() in low for kw in group))
    total = len(must_have)
    fails = []
    if must_not_have:
        for group in must_not_have:
            if any(kw.lower() in low for kw in group):
                fails.append(group[0])
    if fails:
        return passed, total, f"LEAK({','.join(fails)})"
    if passed == total:
        return passed, total, "PERFECT"
    return passed, total, f"PARTIAL({passed}/{total})"

# ─────────────────────────────────────────────────────────────────────────────
# Fast Apply scenarios
# ─────────────────────────────────────────────────────────────────────────────

MERGE_SYSTEM = f"""You are a code merge specialist. You receive an original file and a partial edit using "{MARKER}" markers for unchanged sections.
Replace each marker with the corresponding unchanged code from the original. Return ONLY the complete merged file. No explanations, no markdown fences, no commentary."""

FA_SMALL_ORIGINAL = '''export function add(a: number, b: number): number {
  return a + b;
}

export function subtract(a: number, b: number): number {
  return a - b;
}

export function multiply(a: number, b: number): number {
  return a * b;
}

export function divide(a: number, b: number): number {
  return a / b;
}

export function modulo(a: number, b: number): number {
  return a % b;
}

export function power(a: number, b: number): number {
  return Math.pow(a, b);
}'''

FA_SMALL_EDIT = f'''{MARKER}
export function divide(a: number, b: number): number {{
  if (b === 0) throw new Error("Division by zero");
  return a / b;
}}
{MARKER}'''

FA_SMALL_CHECKS = [
    ("Division by zero",),      # guard added
    ("export function add",),   # preserved
    ("export function subtract",),
    ("export function multiply",),
    ("Math.pow",),              # power preserved
    ("export function modulo",),
]
FA_SMALL_MUST_NOT = [(MARKER,)]

FA_MEDIUM_ORIGINAL = '''import { Request, Response, NextFunction } from "express";
import { UserRepository } from "../repositories/UserRepository";
import { AuthService } from "../services/AuthService";
import { Logger } from "../utils/Logger";
import { ValidationError, NotFoundError } from "../errors";

const logger = new Logger("UserController");

export class UserController {
  private userRepo: UserRepository;
  private authService: AuthService;

  constructor(userRepo: UserRepository, authService: AuthService) {
    this.userRepo = userRepo;
    this.authService = authService;
  }

  async getUser(req: Request, res: Response, next: NextFunction) {
    try {
      const userId = req.params.id;
      const user = await this.userRepo.findById(userId);
      if (!user) {
        throw new NotFoundError("User not found");
      }
      res.json({ data: user });
    } catch (error) {
      next(error);
    }
  }

  async createUser(req: Request, res: Response, next: NextFunction) {
    try {
      const { email, name, password } = req.body;
      if (!email || !name || !password) {
        throw new ValidationError("Missing required fields");
      }
      const existing = await this.userRepo.findByEmail(email);
      if (existing) {
        throw new ValidationError("Email already in use");
      }
      const hashedPassword = await this.authService.hashPassword(password);
      const user = await this.userRepo.create({ email, name, password: hashedPassword });
      logger.info("User created", { userId: user.id });
      res.status(201).json({ data: user });
    } catch (error) {
      next(error);
    }
  }

  async updateUser(req: Request, res: Response, next: NextFunction) {
    try {
      const userId = req.params.id;
      const updates = req.body;
      const user = await this.userRepo.findById(userId);
      if (!user) {
        throw new NotFoundError("User not found");
      }
      const updated = await this.userRepo.update(userId, updates);
      logger.info("User updated", { userId });
      res.json({ data: updated });
    } catch (error) {
      next(error);
    }
  }

  async deleteUser(req: Request, res: Response, next: NextFunction) {
    try {
      const userId = req.params.id;
      const user = await this.userRepo.findById(userId);
      if (!user) {
        throw new NotFoundError("User not found");
      }
      await this.userRepo.delete(userId);
      logger.info("User deleted", { userId });
      res.status(204).send();
    } catch (error) {
      next(error);
    }
  }

  async listUsers(req: Request, res: Response, next: NextFunction) {
    try {
      const page = parseInt(req.query.page as string) || 1;
      const limit = parseInt(req.query.limit as string) || 20;
      const users = await this.userRepo.findAll({ page, limit });
      res.json({ data: users.items, meta: { page, limit, total: users.total } });
    } catch (error) {
      next(error);
    }
  }
}'''

FA_MEDIUM_EDIT = f'''{MARKER}
  async getUser(req: Request, res: Response, next: NextFunction) {{
    try {{
      const userId = req.params.id;
      if (!userId.match(/^[a-f0-9-]{{36}}$/)) {{
        throw new ValidationError("Invalid user ID format");
      }}
      const user = await this.userRepo.findById(userId);
      if (!user) {{
        throw new NotFoundError("User not found");
      }}
      res.json({{ data: user, timestamp: new Date().toISOString() }});
    }} catch (error) {{
      next(error);
    }}
  }}
{MARKER}
  async deleteUser(req: Request, res: Response, next: NextFunction) {{
    try {{
      const userId = req.params.id;
      const user = await this.userRepo.findById(userId);
      if (!user) {{
        throw new NotFoundError("User not found");
      }}
      await this.userRepo.softDelete(userId);
      logger.warn("User soft-deleted", {{ userId, deletedBy: req.user?.id }});
      res.status(204).send();
    }} catch (error) {{
      next(error);
    }}
  }}
{MARKER}'''

FA_MEDIUM_CHECKS = [
    ("match(/^[a-f0-9-]{36}$/)",),  # UUID validation
    ("toISOString()",),              # timestamp
    ("softDelete",),                 # soft delete
    ("logger.warn",),               # warn
    ("deletedBy",),                  # audit
    ("createUser",),                 # preserved
    ("updateUser",),                 # preserved
    ("listUsers",),                  # preserved
]
FA_MEDIUM_MUST_NOT = [(MARKER,)]

FA_LARGE_ORIGINAL = '''import express, { Router, Request, Response, NextFunction } from "express";
import { z } from "zod";
import { PrismaClient, Prisma } from "@prisma/client";
import { Redis } from "ioredis";
import pino from "pino";
import { randomUUID } from "crypto";

const prisma = new PrismaClient();
const redis = new Redis(process.env.REDIS_URL!);
const logger = pino({ name: "order-service" });

// Schemas
const CreateOrderSchema = z.object({
  customerId: z.string().uuid(),
  items: z.array(z.object({
    productId: z.string().uuid(),
    quantity: z.number().int().positive(),
    unitPrice: z.number().positive(),
  })).min(1),
  shippingAddress: z.object({
    street: z.string(),
    city: z.string(),
    state: z.string(),
    zip: z.string(),
    country: z.string(),
  }),
  couponCode: z.string().optional(),
});

const UpdateOrderSchema = z.object({
  status: z.enum(["processing", "shipped", "delivered", "cancelled"]),
  trackingNumber: z.string().optional(),
  notes: z.string().optional(),
});

type CreateOrderInput = z.infer<typeof CreateOrderSchema>;
type UpdateOrderInput = z.infer<typeof UpdateOrderSchema>;

// Service
export class OrderService {
  async createOrder(input: CreateOrderInput): Promise<any> {
    const order = await prisma.order.create({
      data: {
        id: randomUUID(),
        customerId: input.customerId,
        status: "pending",
        items: { create: input.items.map(item => ({ ...item, id: randomUUID() })) },
        shippingAddress: input.shippingAddress as any,
        subtotal: input.items.reduce((sum, i) => sum + i.quantity * i.unitPrice, 0),
        tax: 0,
        total: 0,
      },
      include: { items: true },
    });
    order.tax = order.subtotal * 0.1;
    order.total = order.subtotal + order.tax;
    await prisma.order.update({ where: { id: order.id }, data: { tax: order.tax, total: order.total } });
    return order;
  }

  async getOrder(orderId: string): Promise<any> {
    const order = await prisma.order.findUnique({ where: { id: orderId }, include: { items: true } });
    return order;
  }

  async updateOrder(orderId: string, input: UpdateOrderInput): Promise<any> {
    const order = await prisma.order.update({
      where: { id: orderId },
      data: { ...input, updatedAt: new Date() },
      include: { items: true },
    });
    return order;
  }

  async deleteOrder(orderId: string): Promise<void> {
    await prisma.order.delete({ where: { id: orderId } });
  }

  async listOrders(customerId: string, page: number, limit: number): Promise<any> {
    const [orders, total] = await Promise.all([
      prisma.order.findMany({
        where: { customerId },
        include: { items: true },
        skip: (page - 1) * limit,
        take: limit,
        orderBy: { createdAt: "desc" },
      }),
      prisma.order.count({ where: { customerId } }),
    ]);
    return { orders, total, page, limit };
  }

  async applyDiscount(orderId: string, couponCode: string): Promise<any> {
    const order = await prisma.order.findUnique({ where: { id: orderId } });
    if (!order) throw new Error("Order not found");
    const discount = couponCode === "SAVE10" ? 0.1 : couponCode === "SAVE20" ? 0.2 : 0;
    const newTotal = order.subtotal * (1 - discount) + order.tax;
    await prisma.order.update({ where: { id: orderId }, data: { total: newTotal, couponCode } });
    return { ...order, total: newTotal, couponCode };
  }

  async getOrderStats(customerId: string): Promise<any> {
    const stats = await prisma.order.aggregate({
      where: { customerId },
      _count: true,
      _sum: { total: true },
      _avg: { total: true },
    });
    return stats;
  }
}

// Controller
export class OrderController {
  private service = new OrderService();

  async create(req: Request, res: Response, next: NextFunction) {
    try {
      const input = CreateOrderSchema.parse(req.body);
      const order = await this.service.createOrder(input);
      res.status(201).json({ data: order });
    } catch (error) {
      next(error);
    }
  }

  async get(req: Request, res: Response, next: NextFunction) {
    try {
      const order = await this.service.getOrder(req.params.id);
      if (!order) return res.status(404).json({ error: "Order not found" });
      res.json({ data: order });
    } catch (error) {
      next(error);
    }
  }

  async update(req: Request, res: Response, next: NextFunction) {
    try {
      const input = UpdateOrderSchema.parse(req.body);
      const order = await this.service.updateOrder(req.params.id, input);
      res.json({ data: order });
    } catch (error) {
      next(error);
    }
  }

  async delete(req: Request, res: Response, next: NextFunction) {
    try {
      await this.service.deleteOrder(req.params.id);
      res.status(204).send();
    } catch (error) {
      next(error);
    }
  }

  async list(req: Request, res: Response, next: NextFunction) {
    try {
      const page = parseInt(req.query.page as string) || 1;
      const limit = parseInt(req.query.limit as string) || 20;
      const result = await this.service.listOrders(req.params.customerId, page, limit);
      res.json(result);
    } catch (error) {
      next(error);
    }
  }

  async applyDiscount(req: Request, res: Response, next: NextFunction) {
    try {
      const { couponCode } = req.body;
      const result = await this.service.applyDiscount(req.params.id, couponCode);
      res.json({ data: result });
    } catch (error) {
      next(error);
    }
  }

  async stats(req: Request, res: Response, next: NextFunction) {
    try {
      const stats = await this.service.getOrderStats(req.params.customerId);
      res.json({ data: stats });
    } catch (error) {
      next(error);
    }
  }
}

// Router
const router = Router();
const ctrl = new OrderController();
router.post("/orders", (r, s, n) => ctrl.create(r, s, n));
router.get("/orders/:id", (r, s, n) => ctrl.get(r, s, n));
router.put("/orders/:id", (r, s, n) => ctrl.update(r, s, n));
router.delete("/orders/:id", (r, s, n) => ctrl.delete(r, s, n));
router.get("/customers/:customerId/orders", (r, s, n) => ctrl.list(r, s, n));
router.post("/orders/:id/discount", (r, s, n) => ctrl.applyDiscount(r, s, n));
router.get("/customers/:customerId/orders/stats", (r, s, n) => ctrl.stats(r, s, n));
export default router;'''

FA_LARGE_EDIT = f'''{MARKER}
import pino from "pino";
import {{ randomUUID }} from "crypto";
import {{ RateLimiter }} from "../middleware/RateLimiter";
{MARKER}
  async createOrder(input: CreateOrderInput): Promise<any> {{
    const existing = await redis.get(`order-lock:${{input.customerId}}`);
    if (existing) throw new Error("Duplicate order detected — please wait");
    await redis.set(`order-lock:${{input.customerId}}`, "1", "EX", 30);
    try {{
      const order = await prisma.$transaction(async (tx) => {{
        const created = await tx.order.create({{
          data: {{
            id: randomUUID(),
            customerId: input.customerId,
            status: "pending",
            items: {{ create: input.items.map(item => ({{ ...item, id: randomUUID() }})) }},
            shippingAddress: input.shippingAddress as any,
            subtotal: input.items.reduce((sum, i) => sum + i.quantity * i.unitPrice, 0),
            tax: 0,
            total: 0,
          }},
          include: {{ items: true }},
        }});
        created.tax = created.subtotal * 0.1;
        created.total = created.subtotal + created.tax;
        await tx.order.update({{ where: {{ id: created.id }}, data: {{ tax: created.tax, total: created.total }} }});
        return created;
      }});
      logger.info({{ orderId: order.id, customerId: input.customerId, total: order.total }}, "Order created");
      return order;
    }} finally {{
      await redis.del(`order-lock:${{input.customerId}}`);
    }}
  }}
{MARKER}
  async getOrder(orderId: string): Promise<any> {{
    const cached = await redis.get(`order:${{orderId}}`);
    if (cached) return JSON.parse(cached);
    const order = await prisma.order.findUnique({{ where: {{ id: orderId }}, include: {{ items: true }} }});
    if (order) await redis.set(`order:${{orderId}}`, JSON.stringify(order), "EX", 300);
    return order;
  }}
{MARKER}
  async deleteOrder(orderId: string): Promise<void> {{
    await prisma.order.update({{ where: {{ id: orderId }}, data: {{ status: "cancelled", deletedAt: new Date() }} }});
    await redis.del(`order:${{orderId}}`);
    logger.warn({{ orderId }}, "Order soft-deleted");
  }}
{MARKER}'''

FA_LARGE_CHECKS = [
    ("RateLimiter",),                # new import
    ("$transaction",),               # transaction added
    ("order-lock:",),                # redis lock
    ("logger.info",),                # logging on create
    ("redis.get(`order:",),          # cache on get
    ("JSON.parse",),                 # cache deserialization
    ("deletedAt",),                  # soft delete
    ("logger.warn",),               # warn on delete
    ("redis.del",),                  # cache invalidation
    ("applyDiscount",),             # preserved
    ("getOrderStats",),             # preserved
    ("OrderController",),           # preserved
    ("Router()",),                   # preserved
]
FA_LARGE_MUST_NOT = [(MARKER,)]

FAST_APPLY_SCENARIOS = [
    ("Small (30 lines, 1 edit)", FA_SMALL_ORIGINAL, FA_SMALL_EDIT,
     "Add division by zero guard", FA_SMALL_CHECKS, FA_SMALL_MUST_NOT, 1024),
    ("Medium (80 lines, 3 edits)", FA_MEDIUM_ORIGINAL, FA_MEDIUM_EDIT,
     "Add UUID validation, timestamp, soft-delete", FA_MEDIUM_CHECKS, FA_MEDIUM_MUST_NOT, 4096),
    ("Large (200+ lines, 5 edits)", FA_LARGE_ORIGINAL, FA_LARGE_EDIT,
     "Add transaction, redis lock, caching, soft-delete, logging", FA_LARGE_CHECKS, FA_LARGE_MUST_NOT, 8192),
]

# ─────────────────────────────────────────────────────────────────────────────
# Compaction scenario
# ─────────────────────────────────────────────────────────────────────────────

COMPACT_SYSTEM = """You are a conversation compactor for an AI coding agent. Summarize the conversation below, preserving:
1. ALL file paths mentioned (exact paths)
2. ALL decisions made and changes applied
3. ALL errors encountered and how they were resolved
4. Pending next steps

Be concise but complete. Target ~500 tokens. Use bullet points. Group by topic."""

COMPACT_CONVERSATION = (
    "User: Fix the authentication bug - users are getting logged out randomly.\n\n"
    "Assistant: I'll investigate the auth system. Let me search for the relevant files.\n\n"
    "[Tool: grep] Pattern: 'token.*expir|session.*timeout|logout' in src/\n"
    "Results:\n"
    "src/auth/AuthService.ts:45:  const tokenExpiry = 15 * 60; // 15 minutes\n"
    "src/auth/AuthService.ts:67:  async refreshToken(token: string) {\n"
    "src/auth/AuthMiddleware.ts:23:  if (decoded.exp < Date.now() / 1000) {\n"
    "src/auth/AuthMiddleware.ts:24:    return res.status(401).json({ error: 'Token expired' });\n"
    "src/auth/AuthRepository.ts:34:  await redis.set(`refresh:${userId}`, token, 'EX', 604800);\n"
    "src/shared/redis.ts:12:  const client = new Redis({ host: 'localhost', port: 6379 });\n"
    "src/shared/redis.ts:18:  client.on('error', (err) => logger.error('Redis error', err));\n"
    "src/users/UserService.ts:89:  async updateLastLogin(userId: string) {\n\n"
    "[Tool: read] File: src/auth/AuthMiddleware.ts\n"
    "```typescript\n"
    "import jwt from 'jsonwebtoken';\n"
    "import { Redis } from 'ioredis';\n"
    "\n"
    "export const authMiddleware = async (req, res, next) => {\n"
    "  const token = req.headers.authorization?.split(' ')[1];\n"
    "  if (!token) return res.status(401).json({ error: 'No token' });\n"
    "  try {\n"
    "    const decoded = jwt.verify(token, process.env.JWT_SECRET);\n"
    "    if (decoded.exp < Date.now() / 1000) {\n"
    "      return res.status(401).json({ error: 'Token expired' });\n"
    "    }\n"
    "    const blacklisted = await redis.get(`blacklist:${token}`);\n"
    "    if (blacklisted) return res.status(401).json({ error: 'Token revoked' });\n"
    "    req.user = decoded;\n"
    "    next();\n"
    "  } catch (err) {\n"
    "    return res.status(401).json({ error: 'Invalid token' });\n"
    "  }\n"
    "};\n"
    "```\n\n"
    "Assistant: Found the issue. The AuthMiddleware checks `decoded.exp < Date.now() / 1000` AFTER `jwt.verify()` already validated expiry. But the real bug is in AuthService.ts - the refresh token flow.\n\n"
    "[Tool: read] File: src/auth/AuthService.ts (lines 60-90)\n"
    "```typescript\n"
    "async refreshToken(refreshToken: string): Promise<TokenPair> {\n"
    "  const stored = await this.redis.get(`refresh:${refreshToken}`);\n"
    "  if (!stored) throw new UnauthorizedError('Invalid refresh token');\n"
    "  const userId = stored;\n"
    "  // BUG: not deleting old refresh token before issuing new one\n"
    "  const newAccess = this.generateAccessToken(userId);\n"
    "  const newRefresh = this.generateRefreshToken();\n"
    "  await this.redis.set(`refresh:${newRefresh}`, userId, 'EX', 604800);\n"
    "  return { accessToken: newAccess, refreshToken: newRefresh };\n"
    "}\n"
    "```\n\n"
    "Assistant: Root cause identified: the refresh endpoint issues a new refresh token but does NOT delete the old one from Redis. This creates a race condition during concurrent requests:\n\n"
    "1. Request A sends refresh token R1\n"
    "2. Request B sends refresh token R1 (concurrent tab)\n"
    "3. Request A creates R2, does NOT delete R1\n"
    "4. Request B creates R3, does NOT delete R1\n"
    "5. Now R1, R2, R3 all exist. User has R3, but R2 is orphaned.\n"
    "6. When R3 expires, user tries R2 (stored in another tab) - fails.\n\n"
    "[Tool: edit] File: src/auth/AuthService.ts\n"
    "Applied: Added `await this.redis.del('refresh:${refreshToken}')` before issuing new tokens. Also added a Redis lock `refresh-lock:${userId}` with 5s TTL to serialize concurrent refresh attempts.\n\n"
    "Assistant: Fix applied to src/auth/AuthService.ts. Also noticed the redundant expiry check in AuthMiddleware.ts (jwt.verify already checks exp). Removed it to simplify. \n\n"
    "Next steps: Need to add rate limiting to the /refresh endpoint and write integration tests for concurrent refresh scenarios. Also should add monitoring for orphaned refresh tokens in Redis."
)

COMPACT_CHECKS = [
    ("src/auth/AuthService.ts",),                        # file path preserved
    ("src/auth/AuthMiddleware.ts",),                      # file path preserved
    ("src/shared/redis.ts",),                             # file path preserved
    ("refresh token", "refresh"),                         # core topic
    ("race condition", "concurrent"),                     # root cause
    ("redis.del", "delete", "delet"),                     # fix applied
    ("lock", "serialize"),                                # fix detail
    ("rate limit",),                                      # next step
    ("test", "integration"),                              # next step
]
# ─────────────────────────────────────────────────────────────────────────────
# Parallel runner with retry + circuit breaker
# ─────────────────────────────────────────────────────────────────────────────

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

MAX_WORKERS = 6
MAX_RETRIES = 2
CIRCUIT_BREAKER_THRESHOLD = 3

_print_lock = threading.Lock()
_circuit = {}  # model -> consecutive failures
_circuit_lock = threading.Lock()


def safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)
        sys.stdout.flush()


def is_circuit_open(model):
    with _circuit_lock:
        return _circuit.get(model, 0) >= CIRCUIT_BREAKER_THRESHOLD


def record_result(model, success):
    with _circuit_lock:
        if success:
            _circuit[model] = 0
        else:
            _circuit[model] = _circuit.get(model, 0) + 1


def call_with_retry(model, system, user, max_tokens=4096, timeout=TIMEOUT):
    if is_circuit_open(model):
        return {"ok": False, "error": "circuit open", "time": 0}
    for attempt in range(1 + MAX_RETRIES):
        r = call(model, system, user, max_tokens, timeout)
        if r["ok"]:
            record_result(model, True)
            return r
        if "429" in r.get("error", ""):
            time.sleep(2 ** attempt)
            continue
        if "timed out" in r.get("error", "").lower() and attempt < MAX_RETRIES:
            continue
        break
    record_result(model, False)
    return r


def run_scenario_parallel(scenario_label, models, build_args_fn, score_fn):
    safe_print(f"\n{'=' * 105}")
    safe_print(f"BENCHMARK: {scenario_label}")
    safe_print(f"{'=' * 105}")

    results = []
    completed = [0]
    total = len(models)

    def task(m):
        sys_msg, usr_msg, max_tok = build_args_fn(m)
        r = call_with_retry(m, sys_msg, usr_msg, max_tok)
        row = score_fn(m, r)
        completed[0] += 1
        return row

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(task, m): m for m in models}
        for f in as_completed(futures):
            row = f.result()
            results.append(row)

    results.sort(key=lambda x: (0 if x.get("quality") == "PERFECT" else 1, x.get("time", 999)))
    return results


def run_fast_apply():
    all_results = {}
    for scenario_name, original, edit, instructions, checks, must_not, max_tok in FAST_APPLY_SCENARIOS:
        user_msg = f"<original>\n{original}\n</original>\n\n<edit>\n{edit}\n</edit>\n\nInstructions: {instructions}\n\nReturn the complete merged file:"
        orig_lines = len(original.split("\n"))

        def build_args(m, _u=user_msg, _mt=max_tok):
            return MERGE_SYSTEM, _u, _mt

        def score(m, r, _checks=checks, _mn=must_not, _ol=orig_lines):
            if not r["ok"]:
                safe_print(f"  {m:<30} {'FAIL':>6} {r.get('error','')[:40]}")
                return {"model": m, "ok": False, "time": r["time"], "error": r.get("error", ""), "quality": "FAIL"}
            merged = r["content"]
            ml = len(merged.split("\n"))
            if _ol > 0 and ml < _ol * 0.4:
                q = "TRUNCATED"
                p, t = 0, len(_checks)
            else:
                p, t, q = score_checks(merged, _checks, _mn)
            tps = round(r["tokens_out"] / r["time"], 1) if r["time"] > 0 else 0
            safe_print(f"  {m:<30} {r['time']:>5.1f}s {r['tokens_in']:>7} {r['tokens_out']:>7} {tps:>6.1f} {q:>14}")
            return {"model": m, "ok": True, "time": r["time"], "tokens_in": r["tokens_in"],
                    "tokens_out": r["tokens_out"], "tps": tps, "passed": p, "total": t, "quality": q}

        results = run_scenario_parallel(f"Fast Apply — {scenario_name}", MODELS, build_args, score)
        all_results[scenario_name] = results

        perfect = [r for r in results if r.get("quality") == "PERFECT"]
        safe_print(f"  → {len(perfect)}/{len(results)} PERFECT")

    return all_results


def run_compaction():
    user_msg = f"Summarize this coding agent conversation:\n\n{COMPACT_CONVERSATION}"

    def build_args(m):
        return COMPACT_SYSTEM, user_msg, 1024

    def score(m, r):
        if not r["ok"]:
            safe_print(f"  {m:<30} {'FAIL':>6} {r.get('error','')[:40]}")
            return {"model": m, "ok": False, "time": r["time"], "error": r.get("error", ""), "quality": "FAIL"}
        p, t, q = score_checks(r["content"], COMPACT_CHECKS)
        tps = round(r["tokens_out"] / r["time"], 1) if r["time"] > 0 else 0
        ratio = round(r["tokens_out"] / r["tokens_in"], 2) if r["tokens_in"] > 0 else 0
        safe_print(f"  {m:<30} {r['time']:>5.1f}s {r['tokens_in']:>7} {r['tokens_out']:>7} {tps:>6.1f} {ratio:>5.2f} {q:>14}")
        return {"model": m, "ok": True, "time": r["time"], "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"], "tps": tps, "ratio": ratio,
                "passed": p, "total": t, "quality": q}

    results = run_scenario_parallel("Compaction", MODELS, build_args, score)

    perfect = [r for r in results if r.get("quality") == "PERFECT"]
    safe_print(f"  → {len(perfect)}/{len(results)} PERFECT")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Recommendations + output
# ─────────────────────────────────────────────────────────────────────────────

def print_recommendations(fa_results, compact_results):
    print(f"\n{'=' * 100}")
    print("RECOMMENDATIONS")
    print(f"{'=' * 100}")

    print("\n## Fast Apply")
    model_scores = {}
    for scenario, results in fa_results.items():
        for r in results:
            if not r.get("ok"):
                continue
            m = r["model"]
            if m not in model_scores:
                model_scores[m] = {"perfect": 0, "total": 0, "avg_time": 0, "avg_tps": 0, "scenarios": 0}
            model_scores[m]["total"] += 1
            model_scores[m]["scenarios"] += 1
            model_scores[m]["avg_time"] += r["time"]
            model_scores[m]["avg_tps"] += r["tps"]
            if r["quality"] == "PERFECT":
                model_scores[m]["perfect"] += 1

    for m in model_scores:
        s = model_scores[m]
        s["avg_time"] = round(s["avg_time"] / s["scenarios"], 1) if s["scenarios"] > 0 else 999
        s["avg_tps"] = round(s["avg_tps"] / s["scenarios"], 1) if s["scenarios"] > 0 else 0

    ranked = sorted(model_scores.items(), key=lambda x: (-x[1]["perfect"], x[1]["avg_time"], -x[1]["avg_tps"]))
    print(f"{'MODEL':<30} {'PERFECT':>8} {'AVG_TIME':>9} {'AVG_TOK/S':>10}")
    print("-" * 60)
    for m, s in ranked[:10]:
        print(f"{m:<30} {s['perfect']}/{s['total']:>5} {s['avg_time']:>8.1f}s {s['avg_tps']:>9.1f}")

    if ranked:
        best = ranked[0]
        print(f"\n  >> RECOMMENDED for fast_apply: {best[0]} ({best[1]['perfect']}/{best[1]['total']} PERFECT, {best[1]['avg_time']}s avg)")

    print("\n## Compaction")
    working = [r for r in compact_results if r.get("ok") and r["quality"] == "PERFECT"]
    partial = [r for r in compact_results if r.get("ok") and r["quality"] not in ("PERFECT", "FAIL")]

    if working:
        ranked_c = sorted(working, key=lambda x: (x["ratio"], x["time"]))
        print(f"{'MODEL':<30} {'TIME':>6} {'RATIO':>7} {'TOK/S':>7} {'QUALITY':>14}")
        print("-" * 80)
        for r in ranked_c:
            print(f"{r['model']:<30} {r['time']:>5.1f}s {r['ratio']:>6.2f} {r['tps']:>6.1f} {r['quality']:>14}")
        print(f"\n  >> RECOMMENDED for compaction: {ranked_c[0]['model']} (ratio {ranked_c[0]['ratio']}, {ranked_c[0]['time']}s)")
    elif partial:
        ranked_c = sorted(partial, key=lambda x: (-x["passed"], x.get("ratio", 99), x["time"]))
        print("  No PERFECT results. Best partial:")
        for r in ranked_c[:5]:
            print(f"  {r['model']:<30} {r['quality']:>14} ratio={r.get('ratio','?')} {r['time']}s")


def save_markdown(fa_results, compact_results):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [
        f"# OpenCode Benchmark Results",
        f"",
        f"> Generated: {ts}",
        f"> Proxy: `{PROXY}`",
        f"> Models tested: {len(MODELS)}",
        f"> Concurrency: {MAX_WORKERS} threads, {MAX_RETRIES} retries, circuit breaker at {CIRCUIT_BREAKER_THRESHOLD} failures",
        f"",
    ]

    for scenario, results in fa_results.items():
        lines.append(f"## Fast Apply — {scenario}")
        lines.append("")
        lines.append("| Model | Time | Tokens In | Tokens Out | Tok/s | Quality |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for r in sorted(results, key=lambda x: (0 if x.get("quality") == "PERFECT" else 1, x.get("time", 999))):
            if r.get("ok"):
                lines.append(f"| {r['model']} | {r['time']}s | {r.get('tokens_in',0):,} | {r.get('tokens_out',0):,} | {r.get('tps',0)} | {r['quality']} |")
            else:
                lines.append(f"| {r['model']} | {r['time']}s | — | — | — | FAIL ({r.get('error','')[:30]}) |")
        lines.append("")

    if compact_results:
        lines.append("## Compaction")
        lines.append("")
        lines.append("| Model | Time | Tokens In | Tokens Out | Tok/s | Ratio | Quality |")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for r in sorted(compact_results, key=lambda x: (0 if x.get("quality") == "PERFECT" else 1, x.get("ratio", 99), x.get("time", 999))):
            if r.get("ok"):
                lines.append(f"| {r['model']} | {r['time']}s | {r.get('tokens_in',0):,} | {r.get('tokens_out',0):,} | {r.get('tps',0)} | {r.get('ratio',0)} | {r['quality']} |")
            else:
                lines.append(f"| {r['model']} | {r['time']}s | — | — | — | — | FAIL |")
        lines.append("")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BENCHMARK.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"\nResults saved to {path}")


def main():
    args = set(sys.argv[1:])
    fast_only = "--fast-apply-only" in args
    compact_only = "--compaction-only" in args
    do_save = "--save" in args

    if not API_KEY:
        print("ERROR: FLOW_API_KEY not set")
        sys.exit(1)

    total_calls = 0
    if not compact_only:
        total_calls += len(MODELS) * len(FAST_APPLY_SCENARIOS)
    if not fast_only:
        total_calls += len(MODELS)

    print(f"OpenCode Benchmark Suite (parallel)")
    print(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Proxy: {PROXY}")
    print(f"Models: {len(MODELS)} | Calls: {total_calls} | Workers: {MAX_WORKERS} | Retries: {MAX_RETRIES}")

    t0 = time.time()
    fa_results = {}
    compact_results = []

    if not compact_only:
        fa_results = run_fast_apply()
    if not fast_only:
        compact_results = run_compaction()

    elapsed = round(time.time() - t0, 1)
    print(f"\nTotal time: {elapsed}s ({total_calls} calls, {round(total_calls/elapsed*60, 1)} calls/min)")

    print_recommendations(fa_results, compact_results)

    if do_save:
        save_markdown(fa_results, compact_results)


if __name__ == "__main__":
    main()
