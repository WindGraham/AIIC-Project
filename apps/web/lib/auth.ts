/** Server-side auth helpers. The session token is stored in an httpOnly cookie
 * and forwarded to the agent API as a Bearer token. These run only in server
 * components / route handlers (never in the browser). */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const TOKEN_COOKIE = "pd_session";

export async function getSessionToken(): Promise<string> {
  try {
    const cookieStore = await cookies();
    return cookieStore.get(TOKEN_COOKIE)?.value || "";
  } catch {
    return "";
  }
}

export function setSessionCookie(response: NextResponse, token: string): void {
  response.cookies.set(TOKEN_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

export function clearSessionCookie(response: NextResponse): void {
  response.cookies.set(TOKEN_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
}
