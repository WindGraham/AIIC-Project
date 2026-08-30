import { NextRequest, NextResponse } from "next/server";
import { llmPing } from "@/lib/agent";

/** LLM 接口连通性测试：发文本 → 看模型是否返回。 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  try {
    return NextResponse.json(await llmPing(body));
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 502 });
  }
}
