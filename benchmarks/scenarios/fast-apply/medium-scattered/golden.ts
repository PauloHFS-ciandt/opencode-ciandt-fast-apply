import { Request, Response } from "express";
import { UserRepository } from "../repositories/UserRepository";
import { logger } from "../lib/logger";

const userRepository = new UserRepository();

export class UserController {
  async getUser(req: Request, res: Response): Promise<void> {
    const { id } = req.params;

    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
      res.status(400).json({ error: "Invalid user ID format" });
      return;
    }

    try {
      const user = await userRepository.findById(id);

      if (!user) {
        res.status(404).json({ error: "User not found" });
        return;
      }

      res.status(200).json({ data: user, retrievedAt: new Date().toISOString() });
    } catch (err) {
      logger.error({ err }, "Failed to get user");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async createUser(req: Request, res: Response): Promise<void> {
    const { name, email, role } = req.body;

    try {
      const existing = await userRepository.findByEmail(email);
      if (existing) {
        res.status(409).json({ error: "Email already in use" });
        return;
      }

      const user = await userRepository.create({ name, email, role });
      res.status(201).json({ data: user });
    } catch (err) {
      logger.error({ err }, "Failed to create user");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async updateUser(req: Request, res: Response): Promise<void> {
    const { id } = req.params;
    const { name, role } = req.body;

    try {
      const user = await userRepository.update(id, { name, role });

      if (!user) {
        res.status(404).json({ error: "User not found" });
        return;
      }

      res.status(200).json({ data: user });
    } catch (err) {
      logger.error({ err }, "Failed to update user");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async deleteUser(req: Request, res: Response): Promise<void> {
    const { id } = req.params;

    try {
      await userRepository.softDelete(id);
      logger.warn({ userId: id }, "User soft-deleted");
      res.status(204).send();
    } catch (err) {
      logger.error({ err }, "Failed to delete user");
      res.status(500).json({ error: "Internal server error" });
    }
  }

  async listUsers(req: Request, res: Response): Promise<void> {
    const { page = "1", limit = "20" } = req.query as Record<string, string>;

    try {
      const users = await userRepository.findAll({
        page: parseInt(page, 10),
        limit: parseInt(limit, 10),
      });

      res.status(200).json({ data: users });
    } catch (err) {
      logger.error({ err }, "Failed to list users");
      res.status(500).json({ error: "Internal server error" });
    }
  }
}
