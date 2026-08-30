import { z } from "zod";

/*
 * @aiic/shared — typed contract shared between the Next.js web app and the
 * Python agent. This mirrors apps/agent/src/agent/contracts.py (Pydantic).
 *
 * Design note: the interview is driven by a PLAN + a cursor + a scorecard
 * (data, not a hard state machine). The "interviewer_os" / brain-leak is the
 * reverse-engineering surface that is ONLY surfaced in the post-interview
 * report, never during the live session.
 */

// ---------------------------------------------------------------------------
// Sources (info search) & job/company profile
// ---------------------------------------------------------------------------
export const Source = z.object({
  title: z.string(),
  url: z.string(),
  snippet: z.string(),
  provider: z.enum(["search-engine", "nowcoder", "xiaohongshu", "zhihu", "tavily", "playbook"]),
});
export type Source = z.infer<typeof Source>;

export const CandidateProfile = z.object({
  name: z.string(),
  headline: z.string(),
  /** ~120-char compressed summary (lean prompt uses only this) */
  summary: z.string(),
  skills: z.array(z.string()),
  experience: z.array(z.object({
    company: z.string(),
    role: z.string(),
    duration: z.string(),
    bullets: z.array(z.string()),
  })),
  projects: z.array(z.object({
    name: z.string(),
    role: z.string(),
    bullets: z.array(z.string()),
  })),
  level: z.enum(["junior", "mid", "senior", "staff"]),
  resume_hash: z.string(),
});
export type CandidateProfile = z.infer<typeof CandidateProfile>;

export const JobSpec = z.object({
  position: z.string(),
  seniority: z.enum(["junior", "mid", "senior", "staff"]),
  company: z.string(),
  must_have: z.array(z.string()),
  nice_to_have: z.array(z.string()),
  tech_stack: z.array(z.string()),
  responsibilities: z.array(z.string()),
  jd_text: z.string(),
});
export type JobSpec = z.infer<typeof JobSpec>;

export const CompanyIntel = z.object({
  summary: z.string(),
  tech_stack: z.array(z.string()),
  values: z.array(z.string()),
  interview_process: z.string(),
  recent_news: z.array(z.string()),
  culture_notes: z.string(),
  coding_tendency: z.object({
    prefers_live_coding: z.boolean(),
    high_freq_topics: z.array(z.string()),
    platform: z.enum(["leetcode", "coderpad", "local", "unknown"]),
  }),
  missing_company_info: z.boolean(),
  sources: z.array(Source),
});
export type CompanyIntel = z.infer<typeof CompanyIntel>;

export const GapAnalysis = z.object({
  strengths: z.array(z.string()),
  gaps: z.array(z.string()),
  probe_targets: z.array(z.string()),
  missing_skills: z.array(z.string()),
});
export type GapAnalysis = z.infer<typeof GapAnalysis>;

// ---------------------------------------------------------------------------
// Question plan (built in prep; the live agent walks it via tools)
// ---------------------------------------------------------------------------
export const RubricItem = z.object({
  point: z.string(),
  weight: z.number(),
});
export type RubricItem = z.infer<typeof RubricItem>;

export const PlannedQuestion = z.object({
  id: z.string(),
  section: z.enum(["intro", "behavioral", "technical", "coding", "wrap"]),
  text: z.string(),
  /** 1..5 rising difficulty curve */
  difficulty: z.number().min(1).max(5),
  rubric: z.array(RubricItem),
  followups: z.array(z.string()),
  target_competency: z.string(),
  /** coding section only: offline problem reference */
  problem_id: z.string().optional(),
});
export type PlannedQuestion = z.infer<typeof PlannedQuestion>;

export const QuestionPlan = z.object({
  sections_order: z.array(z.enum(["intro", "behavioral", "technical", "coding", "wrap"])),
  questions: z.array(PlannedQuestion),
});
export type QuestionPlan = z.infer<typeof QuestionPlan>;

// ---------------------------------------------------------------------------
// Scorecard / answers / interviewer_os (post-only brain-leak)
// ---------------------------------------------------------------------------
export const ScoreItem = z.object({
  competency: z.string(),
  score: z.number().min(0).max(5),
  evidence: z.string(),
  level: z.enum(["below", "meets", "exceeds"]),
});
export type ScoreItem = z.infer<typeof ScoreItem>;

export const AnswerRecord = z.object({
  question_id: z.string(),
  transcript: z.string(),
  score: z.number().min(0).max(5).optional(),
  status: z.enum(["asked", "answered", "skipped"]),
  started_at: z.string().optional(),
  ended_at: z.string().optional(),
  /** coding section: the final code the agent saw */
  final_code: z.string().optional(),
});
export type AnswerRecord = z.infer<typeof AnswerRecord>;

export const InterviewerOS = z.object({
  hidden_concern: z.string(),
  why_this_question: z.array(z.string()),
  missing_slots: z.array(z.object({
    slot: z.string(),
    evidence: z.string(),
    why_it_matters: z.string(),
    what_i_want_to_hear: z.array(z.string()),
    one_line_advice: z.string(),
  })),
  risk_level: z.enum(["low", "medium", "high"]),
});
export type InterviewerOS = z.infer<typeof InterviewerOS>;

export const InterviewContext = z.object({
  candidate: CandidateProfile,
  job: JobSpec,
  company: CompanyIntel,
  gap: GapAnalysis,
  plan: QuestionPlan,
  cursor: z.number(),
  answers: z.array(AnswerRecord),
  scorecard: z.object({
    overall: z.number().min(0).max(100),
    items: z.array(ScoreItem),
    summary: z.string(),
    next_steps: z.array(z.string()),
    model_answers: z.array(z.string()),
    interviewer_os: InterviewerOS,
  }),
  status: z.enum(["prep", "live", "post", "complete"]),
  persona: z.enum(["peer", "high-peer", "manager"]).optional(),
  mode: z.enum(["text", "ptt", "duplex"]).optional(),
  memory_brief: z.string().optional(),
});
export type InterviewContext = z.infer<typeof InterviewContext>;
