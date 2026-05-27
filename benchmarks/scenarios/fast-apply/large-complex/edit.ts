import { Router, Request, Response } from "express";
import { PrismaClient } from "@prisma/client";
import { z } from "zod";
import { logger } from "../lib/logger";
import { redisClient } from "../lib/redis";

const prisma = new PrismaClient();

// ... existing code ...

export class OrderService {
  async createOrder(input: CreateOrderInput) {
    const lockKey = `order:lock:${input.customerId}`;
    const locked = await redisClient.set(lockKey, "1", { NX: true, EX: 30 });
    if (!locked) {
      throw new Error("Another order is being processed for this customer");
    }

    try {
      const total = input.items.reduce(
        (sum, item) => sum + item.quantity * item.unitPrice,
        0
      );

      const order = await prisma.$transaction(async (tx) => {
        return tx.order.create({
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
      });

      logger.info({ orderId: order.id, customerId: order.customerId }, "Order created");
      return order;
    } finally {
      await redisClient.del(lockKey);
    }
  }

  async getOrder(id: string) {
    const cacheKey = `order:${id}`;
    const cached = await redisClient.get(cacheKey);
    if (cached) {
      return JSON.parse(cached);
    }

    const order = await prisma.order.findUnique({
      where: { id },
      include: { items: true, customer: true },
    });

    if (!order) {
      throw new Error(`Order ${id} not found`);
    }

    await redisClient.set(cacheKey, JSON.stringify(order), { EX: 300 });
    return order;
  }

  // ... existing code ...

  async deleteOrder(id: string) {
    await prisma.order.update({
      where: { id },
      data: { deletedAt: new Date() },
    });
    logger.info({ orderId: id }, "Order soft-deleted");
  }

  // ... existing code ...
}

// ... existing code ...
