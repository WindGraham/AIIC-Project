/** Thin client for the agent API. Never exposes AGENT_API_URL to the browser;
 * only server components / route handlers call this. Falls back gracefully so
 * the app builds & renders without a running agent (offline/mock-first). */

export type AgentHealth = Record<string, unknown>;

export async function health(): Promise<AgentHealth> {
  const base = process.env.AGENT_API_URL || "http://127.0.0.1:8000";
  try {
    const r = await fetch(`${base}/health`, { cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()) as AgentHealth;
  } catch {
    return { status: "unreachable", host: base };
  }
}
