/**
 * Math utility functions for arithmetic operations.
 */

// ... existing code ...

export function divide(a: number, b: number): number {
  if (b === 0) {
    throw new Error("Division by zero is not allowed");
  }
  return a / b;
}

// ... existing code ...
