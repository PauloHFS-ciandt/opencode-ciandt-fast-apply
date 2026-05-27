/**
 * Input validation utilities.
 */

export function validateEmail(value: string): boolean {
  const pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return pattern.test(value.trim());
}

export function validatePhone(value: string): boolean {
  const digits = value.replace(/\D/g, "");
  return digits.length >= 10 && digits.length <= 15;
}

export function validateAge(value: number): boolean {
  return Number.isInteger(value) && value >= 0;
}

export function validateName(value: string): boolean {
  return value.trim().length > 0;
}

export function validateAddress(value: string): boolean {
  return value.trim().length >= 10;
}
