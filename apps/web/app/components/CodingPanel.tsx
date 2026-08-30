"use client";

import { useEffect, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { cpp } from "@codemirror/lang-cpp";
import { javascript } from "@codemirror/lang-javascript";
import { EditorView } from "@codemirror/view";

type Lang = "python" | "cpp" | "javascript";

const LANGS: { value: Lang; label: string; ext: () => any }[] = [
  { value: "cpp", label: "C++", ext: () => cpp() },
  { value: "python", label: "Python", ext: () => python() },
  { value: "javascript", label: "JavaScript", ext: () => javascript() },
];

const EDITOR_THEME = EditorView.theme({
  "&": { backgroundColor: "transparent", fontSize: "13px" },
  ".cm-content": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  ".cm-gutters": { backgroundColor: "rgba(255,255,255,0.03)", borderRight: "1px solid rgba(255,255,255,0.08)" },
});

/**
 * 手撕代码编辑器：CodeMirror 6 —— Python/C++ 语法高亮 + 自动缩进（不做语法纠错）。
 * 写完点「提交给面试官」→ onSubmit(code, language) 交给房间在对话里显示"提交代码"，
 * 并把代码发给 agent 判分/回复。
 */
export default function CodingPanel({
  interviewId,
  onSubmit,
}: {
  interviewId: string;
  onSubmit?: (code: string, language: Lang) => void;
}) {
  const [problem, setProblem] = useState<any>(null);
  const [questionText, setQuestionText] = useState<string>("");
  const [code, setCode] = useState("");
  const [lang, setLang] = useState<Lang>("python");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const d = await (await fetch(`/api/interviews/${interviewId}/problem`)).json();
        setProblem(d.problem);
        setQuestionText(d.question_text || "");
      } catch {
        setErr("无法加载题目");
      }
    })();
  }, [interviewId]);

  function submit() {
    if (busy) return;
    setBusy(true);
    setErr(null);
    // Route through the room so the "提交代码" bubble shows in the conversation and
    // the agent's reply appears there too. Fall back to inline if no onSubmit.
    if (onSubmit) {
      onSubmit(code, lang);
      // Allow the agent's reply to arrive asynchronously; re-enable after a moment.
      setTimeout(() => setBusy(false), 0);
    } else {
      setBusy(false);
    }
  }

  if (err) return <div className="text-red-400 text-sm">{err}</div>;

  const activeExt = (LANGS.find((l) => l.value === lang) || LANGS[0]).ext();

  return (
    <div className="rounded-2xl border border-white/10 p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm text-white/50">✍️ 手撕代码环节</div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-white/40">语言</label>
          <select className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs" value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}>
            {LANGS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
          </select>
        </div>
      </div>

      {problem ? (
        <div className="mb-3">
          <div className="font-semibold">{problem.title} <span className="text-white/40 text-xs">({problem.difficulty})</span></div>
          <p className="text-sm text-white/70 whitespace-pre-wrap mt-1">{problem.description}</p>
          {problem.examples?.slice(0, 2).map((e: any, i: number) => (
            <pre key={i} className="bg-white/5 rounded p-2 text-xs mt-1 overflow-x-auto">输入: {e.input} → 输出: {e.output}</pre>
          ))}
        </div>
      ) : (
        questionText && <p className="text-sm text-white/70">{questionText}</p>
      )}

      <div className="rounded-lg border border-white/10 bg-black/40 overflow-hidden">
        <CodeMirror
          value={code}
          height="220px"
          theme="dark"
          basicSetup={{ highlightActiveLine: true, highlightActiveLineGutter: true }}
          extensions={[activeExt, EDITOR_THEME]}
          onChange={(val) => setCode(val)}
        />
      </div>
      <button onClick={submit} disabled={busy}
        className="mt-2 rounded-lg bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 px-4 py-2 text-sm font-semibold">
        {busy ? "已提交" : "提交给面试官"}
      </button>
    </div>
  );
}
