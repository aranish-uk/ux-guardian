import { NextRequest, NextResponse } from "next/server";
import { createSession, seededCredentialsMatch } from "../../../lib/session";

export async function POST(request: NextRequest) {
  // NextURL normalizes loopback hostnames; Host preserves the browser's authority.
  const host = request.headers.get("host");
  const requestOrigin = `${request.nextUrl.protocol}//${host}`;
  if (!host || request.headers.get("origin") !== requestOrigin) {
    return NextResponse.json({ error: "Invalid request origin" }, { status: 403 });
  }
  if (!process.env.TEST_EMAIL || !process.env.TEST_PASSWORD) {
    return NextResponse.json({ error: "Seeded account is not configured" }, { status: 503 });
  }
  let data: FormData;
  try { data = await request.formData(); }
  catch { return NextResponse.json({ error: "Invalid form" }, { status: 400 }); }
  const email = data.get("email");
  const password = data.get("password");
  if (typeof email !== "string" || typeof password !== "string" || !seededCredentialsMatch(email, password)) {
    return NextResponse.redirect(new URL("/login?error=1", requestOrigin), 303);
  }
  const response = NextResponse.redirect(new URL("/account", requestOrigin), 303);
  response.cookies.set("ux-session", createSession(), {
    httpOnly: true, secure: request.nextUrl.protocol === "https:", sameSite: "lax", path: "/", maxAge: 3600,
  });
  return response;
}
