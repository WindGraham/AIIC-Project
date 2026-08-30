import { NextResponse } from "next/server";
import { getMe } from "@/lib/agent";

export async function GET() {
  const me = await getMe();
  if (!me) return NextResponse.json({ user: null }, { status: 401 });
  return NextResponse.json(me);
}
