import "server-only";
import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const digest = (value: string) => createHash("sha256").update(value).digest();

export function seededCredentialsMatch(email: string, password: string): boolean {
  const expectedEmail = process.env.TEST_EMAIL;
  const expectedPassword = process.env.TEST_PASSWORD;
  if (!expectedEmail || !expectedPassword) return false;
  const emailMatches = timingSafeEqual(digest(email), digest(expectedEmail));
  const passwordMatches = timingSafeEqual(digest(password), digest(expectedPassword));
  return emailMatches && passwordMatches;
}

function signature(payload: string): string {
  const key = process.env.TEST_PASSWORD;
  if (!key || !process.env.TEST_EMAIL) throw new Error("Seeded account is not configured");
  return createHmac("sha256", key).update(`ux-guardian-demo:${payload}`).digest("hex");
}

export function createSession(): string {
  const payload = `${Date.now() + 3_600_000}.${randomBytes(16).toString("hex")}`;
  return `${payload}.${signature(payload)}`;
}

export function validSession(token: string | undefined): boolean {
  if (!token || !process.env.TEST_EMAIL || !process.env.TEST_PASSWORD) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [expiry, nonce, signed] = parts;
  if (!/^\d+$/.test(expiry) || !/^[a-f0-9]{32}$/.test(nonce) || !/^[a-f0-9]{64}$/.test(signed)) return false;
  const remaining = Number(expiry) - Date.now();
  if (remaining <= 0 || remaining > 3_600_000) return false;
  return timingSafeEqual(Buffer.from(signed, "hex"), Buffer.from(signature(`${expiry}.${nonce}`), "hex"));
}
