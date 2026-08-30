/** Server-side client for the agent API. Never exposed to the browser — these
 * are called by server components / route handlers. Falls back gracefully so
 * the app builds & renders without a running agent. */

import { getSessionToken } from "@/lib/auth";

const AGENT_BASE = process.env.AGENT_API_URL || "http://127.0.0.1:8000";

async function call(path: string, init?: RequestInit): Promise<any> {
  const token = await getSessionToken();
  const res = await fetch(`${AGENT_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    // surface the agent's detail message when present
    let msg = `agent ${path} -> ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = String(body.detail);
      else if (body?.error) msg = String(body.error);
    } catch {
      /* no body */
    }
    throw new Error(msg);
  }
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

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export async function register(username: string, password: string) {
  return call("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) });
}

export async function login(username: string, password: string) {
  return call("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
}

export async function logout(token: string) {
  return call("/api/auth/logout", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

export async function getMe(): Promise<{ user: { id: string; username: string } } | null> {
  try {
    return await call("/api/auth/me");
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Resumes
// ---------------------------------------------------------------------------
export type Resume = {
  id: string;
  name: string;
  resume_text: string;
  resume_hash: string;
  skills: string[];
  is_default: boolean;
  created_at: string;
};

export async function listResumes(): Promise<Resume[]> {
  try {
    return await call("/api/resumes");
  } catch {
    return [];
  }
}

export async function createResume(body: { name: string; resume_text: string; skills?: string[]; is_default?: boolean }) {
  return call("/api/resumes", { method: "POST", body: JSON.stringify(body) });
}

export async function updateResume(id: string, body: Partial<{ name: string; resume_text: string; skills: string[]; is_default: boolean }>) {
  return call(`/api/resumes/${id}`, { method: "PUT", body: JSON.stringify(body) });
}

export async function deleteResume(id: string) {
  return call(`/api/resumes/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Bookings / interviews
// ---------------------------------------------------------------------------
export type Booking = {
  id: string;
  name: string;
  resume_id: string;
  resume_text: string;
  company: string;
  position: string;
  jd_text: string;
  scheduled_at: string;
  notes: string;
  has_coding: boolean;
  scenario: string;
  persona: string;
  created_at: string;
  seconds_until_start?: number;
  status?: string;
};

export async function listBookings(): Promise<Booking[]> {
  try {
    return await call("/api/interviews");
  } catch {
    return [];
  }
}

export async function bookInterview(body: Partial<Booking>): Promise<Booking> {
  return call("/api/interviews/book", { method: "POST", body: JSON.stringify(body) });
}

export async function getHistory(): Promise<any[]> {
  try {
    return await call("/api/interviews/history");
  } catch {
    return [];
  }
}

export async function startBooking(bookingId: string): Promise<{ interview_id: string; question: string; plan: any }> {
  return call(`/api/interviews/${bookingId}/start`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Interview brain (existing)
// ---------------------------------------------------------------------------
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

export async function visionAnalyze(body: { image_b64: string; prompt?: string }): Promise<any> {
  return call("/api/vision/analyze", { method: "POST", body: JSON.stringify(body) });
}

export async function getTranscript(interviewId: string): Promise<any> {
  return call(`/api/interviews/${interviewId}/transcript`);
}

export async function getRecap(interviewId: string): Promise<any> {
  return call(`/api/interviews/${interviewId}/recap`);
}

// ---------------------------------------------------------------------------
// Info search capability (public, used by prep — no auth needed here)
// ---------------------------------------------------------------------------
export async function searchSources(body: { query: string; company?: string; position?: string; limit?: number }): Promise<any> {
  return call("/api/search", { method: "POST", body: JSON.stringify(body) });
}

// ---------------------------------------------------------------------------
// LiveKit agent presence (interviewer joins the room as a participant)
// ---------------------------------------------------------------------------
export async function agentJoin(interviewId: string) {
  return call(`/api/interviews/${interviewId}/agent-join`, { method: "POST" });
}

export async function agentLeave(interviewId: string) {
  return call(`/api/interviews/${interviewId}/agent-leave`, { method: "POST" });
}

export async function agentStatus(interviewId: string) {
  return call(`/api/interviews/${interviewId}/agent/status`);
}

export async function agentScreenshare(interviewId: string) {
  return call(`/api/interviews/${interviewId}/agent/screenshare`);
}
