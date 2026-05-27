/**
 * Math utility functions for arithmetic operations.
 */

export function add(a: number, b: number): number {
  return a + b;
}

export function subtract(a: number, b: number): number {
  return a - b;
}

export function multiply(a: number, b: number): number {
  return a * b;
}

export function divide(a: number, b: number): number {
  if (b === 0) {
    throw new Error("Division by zero is not allowed");
  }
  return a / b;
}

export function modulo(a: number, b: number): number {
  return a % b;
}

export function power(base: number, exponent: number): number {
  return Math.pow(base, exponent);
}
