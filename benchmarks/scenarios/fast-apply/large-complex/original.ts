import { Router, Request, Response } from "express";
import { PrismaClient } from "@prisma/client";
import { z } from "zod";
import { logger } from "../lib/logger";

const prisma = new PrismaClient();

// ─── Validation Schemas ───────────────────────────────────────────────────────

const CreateOrderSchema = z.object({
  customerId: z.string().uuid(),
  items: z
    .array(
      z.object({
        productId: z.string().uuid(),
        quantity: z.number().int().positive(),
        unitPrice: z.number().positive(),
      })
    )
    .min(1),
  shippingAddressId: z.string().uuid(),
  notes: z.string().max(500).optional(),
});

const UpdateOrderSchema = z.object({
  status: z.enum(["pending", "confirmed", "shipped", "delivered", "cancelled"]),
  notes: z.string().max(500).optional(),
});

type CreateOrderInput = z.infer<typeof CreateOrderSchema>;
type UpdateOrderInput = z.infer<typeof UpdateOrderSchema>;

// ─── Service ──────────────────────────────────────────────────────────────────

export class OrderService {
  async createOrder(input: CreateOrderInput) {
    const total = input.items.reduce(
      (sum, item) => sum + item.quantity * item.unitPrice,
      0
    );

    const order = await prisma.order.create({
      data: {
        customerId: input.customerId,
        shippingAddressId: input.shippingAddressId,
        notes: input.notes,
        status: "pending",
        total,
        items: {
          create: input.items.map((item) => ({
            productId: item.productId,
            quantity: item.quantity,
            unitPrice: item.unitPrice,
          })),
        },
      },
      include: { items: true },
    });

    logger.info({ orderId: order.id, customerId: order.customerId }, "Order created");
    return order;
  }

  async getOrder(id: string) {
    const order = await prisma.order.findUnique({
      where: { id },
      include: { items: true, customer: true },
    });

    if (!order) {
      throw new Error(`Order ${id} not found`);
    }

    return order;
  }

  async updateOrder(id: string, input: UpdateOrderInput) {
    const order = await prisma.order.update({
      where: { id },
      data: input,
      include: { items: true },
    });

    logger.info({ orderId: id, status: input.status }, "Order updated");
    return order;
  }

  async deleteOrder(id: string) {
    await prisma.order.delete({ where: { id } });
    logger.info({ orderId: id }, "Order deleted");
  }

  async listOrders(customerId: string, page = 1, limit = 20) {
    const [orders, total] = await Promise.all([
      prisma.order.findMany({
        where: { customerId },
        include: { items: true },
        orderBy: { createdAt: "desc" },
        skip: (page - 1) * limit,
        take: limit,
      }),
      prisma.order.count({ where: { customerId } }),
    ]);

    return { orders, total, page, limit };
  }

  async cancelOrder(id: string, reason: string) {
    const order = await prisma.order.findUnique({ where: { id } });

    if (!order) {
      throw new Error(`Order ${id} not found`);
    }

    if (!["pending", "confirmed"].includes(order.status)) {
      throw new Error(`Cannot cancel order in status ${order.status}`);
    }

    const updated = await prisma.order.update({
      where: { id },
      data: { status: "cancelled", notes: reason },
    });

    logger.info({ orderId: id, reason }, "Order cancelled");
    return updated;
  }
}

// ─── Controller ───────────────────────────────────────────────────────────────

const orderService = new OrderService();

export class OrderController {
  async create(req: Request, res: Response): Promise<void> {
    const parsed = CreateOrderSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }

    try {
      const order = await orderService.createOrder(parsed.data);
      res.status(201).json({ data: order });
    } catch (err) {
      logger.error({ err }, "Failed to create order");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async get(req: Request, res: Response): Promise<void> {
    const { id } = req.params;

    try {
      const order = await orderService.getOrder(id);
      res.status(200).json({ data: order });
    } catch (err: any) {
      if (err.message?.includes("not found")) {
        res.status(404).json({ error: err.message });
        return;
      }
      logger.error({ err }, "Failed to get order");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async update(req: Request, res: Response): Promise<void> {
    const { id } = req.params;
    const parsed = UpdateOrderSchema.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: parsed.error.flatten() });
      return;
    }

    try {
      const order = await orderService.updateOrder(id, parsed.data);
      res.status(200).json({ data: order });
    } catch (err) {
      logger.error({ err }, "Failed to update order");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async delete(req: Request, res: Response): Promise<void> {
    const { id } = req.params;

    try {
      await orderService.deleteOrder(id);
      res.status(204).send();
    } catch (err) {
      logger.error({ err }, "Failed to delete order");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async list(req: Request, res: Response): Promise<void> {
    const { customerId } = req.params;
    const { page = "1", limit = "20" } = req.query as Record<string, string>;

    try {
      const result = await orderService.listOrders(
        customerId,
        parseInt(page, 10),
        parseInt(limit, 10)
      );
      res.status(200).json({ data: result });
    } catch (err) {
      logger.error({ err }, "Failed to list orders");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async cancel(req: Request, res: Response): Promise<void> {
    const { id } = req.params;
    const { reason } = req.body;

    if (!reason || typeof reason !== "string") {
      res.status(400).json({ error: "Cancellation reason is required" });
      return;
    }

    try {
      const order = await orderService.cancelOrder(id, reason);
      res.status(200).json({ data: order });
    } catch (err: any) {
      if (err.message?.includes("not found")) {
        res.status(404).json({ error: err.message });
        return;
      }
      if (err.message?.includes("Cannot cancel")) {
        res.status(422).json({ error: err.message });
        return;
      }
      logger.error({ err }, "Failed to cancel order");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async getStats(req: Request, res: Response): Promise<void> {
    const { customerId } = req.params;

    try {
      const stats = await prisma.order.groupBy({
        by: ["status"],
        where: { customerId },
        _count: { id: true },
        _sum: { total: true },
      });

      res.status(200).json({ data: stats });
    } catch (err) {
      logger.error({ err }, "Failed to get order stats");
      res.status(500).json({ error: "Internal server error" });
    }
  }
}

// ─── Router ───────────────────────────────────────────────────────────────────

const controller = new OrderController();
export const orderRouter = Router();

orderRouter.post("/", (req, res) => controller.create(req, res));
orderRouter.get("/:id", (req, res) => controller.get(req, res));
orderRouter.put("/:id", (req, res) => controller.update(req, res));
orderRouter.delete("/:id", (req, res) => controller.delete(req, res));
orderRouter.get("/customer/:customerId", (req, res) => controller.list(req, res));
orderRouter.post("/:id/cancel", (req, res) => controller.cancel(req, res));
orderRouter.get("/customer/:customerId/stats", (req, res) => controller.getStats(req, res));
