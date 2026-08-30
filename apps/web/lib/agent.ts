/** Server-side client for the agent API. Never exposed to the browser — these
 * are called by server components / route handlers. Falls back gracefully so
 * the app builds & renders without a running agent. */

const AGENT_BASE = process.env.AGENT_API_URL || "http://127.0.0.1:8000";

async function call(path: string, init?: RequestInit): Promise<any> {
  const res = await fetch(`${AGENT_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`agent ${path} -> ${res.status}`);
  return res.json();
}

export type AgentHealth = Record<string, unknown>;

export async function health(): Promise<AgentHealth> {
  try {
    return await call("/health");
  } catch {
    return { status: "unreachable", host: AGENT_BASE };
  }
}

export async function prepareInterview(body: {
  resume_text: string;
  jd_text: string;
  company: string;
  position: string;
  seniority?: string;
  lang?: string;
}) {
  return call("/api/interviews/prepare", { method: "POST", body: JSON.stringify(body) });
}

export async function getNext(interviewId: string): Promise<{ question: string | null; done: boolean }> {
  return call(`/api/interviews/${interviewId}/next`);
}

export async function postAnswer(interviewId: string, answer: string): Promise<{ next_question: string | null; done: boolean }> {
  return call(`/api/interviews/${interviewId}/answer`, { method: "POST", body: JSON.stringify({ answer }) });
}

export async function getReport(interviewId: string): Promise<any> {
  return call(`/api/interviews/${interviewId}/report`);
}

export async function voiceAnswer(body: {
  interview_id: string;
  audio_b64?: string;
  format?: string;
}): Promise<any> {
  return call("/api/voice/answer", { method: "POST", body: JSON.stringify(body) });
}

export async function getCodingProblem(interviewId: string): Promise<any> {
  return call(`/api/interviews/${interviewId}/problem`);
}

export async function codingJudge(body: {
  interview_id: string;
  code: string;
  language?: string;
}): Promise<any> {
  return call("/api/coding/judge", { method: "POST", body: JSON.stringify(body) });
}
