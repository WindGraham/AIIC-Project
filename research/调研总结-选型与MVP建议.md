# 调研总结 · 选型建议与 MVP 落地方向

> 面向 16 小时「AI 模拟面试官」项目。在 `分析-*` 各文件对 26 个开源项目充分取证的基础上，这里给出"我们该做什么、用哪些成熟模块、怎么在 10 小时内做出差异化闭环"的结论。
> 定位前提（来自用户选择）：**先聚焦「实习面试」场景 + 语音交互形态**；差异化要能回答"为什么比直接用 ChatGPT 更好"。

## 一、一句话结论

> 现有开源 AI 模拟面试项目绝大多数停在「**一问一答 + 打分的 AI 问答**」，真正的竞争空白是「**岗位人才画像 + 拟真追问/压力面 + 可执行的逐题复盘**」。我们要做的不是再做一个 AI 出题器，而是做一个**让学生 get 到面试官意图、并看到自己进步的训练闭环**。

## 二、交互形态：语音做薄层，文字闭环打底

调研里所有"语音面试官"的真实实现分四档，成本/复杂度差异巨大：

| 档位 | 代表 | 说明 | 对 16h 的取舍 |
|------|------|------|--------------|
| 全双工真语音（LiveKit agent） | Assess-AI、interview-ai-assistant | 实时打断、字幕 data channel | 需 LiveKit Cloud+付费 STT/TTS+自写客户端，太重 |
| 半实时/轮询 | warmscreen | LiveKit token + Deepgram 流式 + ElevenLabs 音频 buffer + 前端轮询 | 中等，仍有云依赖与轮询延迟 |
| 裸 WS 桥云 Live API | socratic_mirror | FastAPI WS 桥 Gemini Live，浏览器 Web Speech 兜底 | 省钱但延迟/稳定性压云 API |
| **听写式（本地）** | **grillkit、offerMaster** | **本地 faster-whisper（缓冲转写）+ 本地/免费 TTS（Piper/edge-tts）+ push-to-talk** | **最适合 16h：零 API 依赖、成本≈¥0.3/场** |

**结论**：用 **offerMaster 的"听写式 push-to-talk"** 模式做语音（本地 Whisper 转写 + edge-tts 出声），把语音做成"薄薄一层"叠加在扎实的文字闭环上。不要为全双工实时语音投入大量时间——那是加分项不是基础线。

## 三、技术栈选型（综合最优）

| 层 | 选型 | 依据（可复用模块来源） |
|----|------|----------------------|
| 前端 | Next.js / Vite + React + Tailwind | offerMaster、lhw12138、DeepInterview 均是此栈；组件生态成熟 |
| 后端 | FastAPI（Python） | offerMaster、grillkit、Assess-AI、socratic_mirror、Seekr 均用；ASR/TTS/PDF 生态最全 |
| 状态机 | **确定性轮询状态机**（FASTAPI 驱动）而非 LangGraph 全自动图 | offerMaster 注释自述 + grillkit/seekr 验证：**回合制面试是"人声门控"，不需要全自主 agent**；LangGraph 在多数项目里是摆设 |
| LLM | **OpenAI 兼容协议**，默认 DeepSeek（可切 Kimi/Qwen/GPT/本地 Ollama） | offerMaster、lhw12138、grillkit、intervio 全部用它，成本 ≈¥0.3/场 |
| STT | 本地 faster-whisper（默认，免费离线）| offerMaster `voice.py`、grillkit | 可选火山/豆包流式 ASR（更准，付费）|
| TTS | edge-tts（默认免费）/ 浏览器 speechSynthesis | offerMaster、lhw12138 |
| 评分+复盘 | 结构化 JSON (zod/pydantic) + rubric + 原话证据 + improvedAnswer | lhw12138 `prompts.ts`（最完整）、grillkit `evaluator_prompts.py`、offerMaster |
| 题库 | 岗位×题目 JSON（带参考答案）| lhw12138 `question-banks/*.json`（100题/岗，可直接借）|
| 存储 | 本地 SQLite / localStorage（游客免注册）| lhw12138、intervio、offerMaster（避免上重数据库）|
| 代码执行（可选加分）| 客户端直连公共 Piston（emkc.org）| 三个视频工具仓库全部这么做，20 行封装 |
| 协作编辑器（可选加分）| Yjs + MonacoBinding | interview_platform1 `CodeEditor.jsx`（事实标准）|

**刻意不做的（写进 Memo）**：全双工实时语音、LiveKit/云 ASR/TTS、数字人头像、账号体系/支付、视频+现场写代码全量（作为加分项而非基线）。这些要么成本高要么干扰核心闭环。

## 四、产品核心闭环（MVP，10 小时可跑通）

1. **上传/粘贴简历 + 目标岗位 JD**（或选预设岗位）。
2. **生成"岗位人才画像"**：AI 从 JD + 公开信息提取该岗位看重的**能力侧重点/人才画像**，并**映射到用户简历**——告诉用户"该重点表现哪些方面"。（这是 Road 类用户最痛的需求，现有开源几乎空白，是最大差异化。）
3. **基于画像 + 简历个性化出题**，拟真追问（引用原话深挖、判断知识边界、必要时**压力面打断**），多轮。
4. **逐题结构化评分**（多维 + 原话证据 + 标准答题框架 + 改写示例），并做**最弱维度专项训练 + 逐题重答**。
5. **复盘报告**：弱点雷达图、进步曲线、可执行建议，支持 PDF 分享。（回放复盘是保研/压力面用户的刚需。）

## 五、三个差异化抓手（把"为什么比 ChatGPT 好"讲清楚）

1. **岗位人才画像（telling you what to show）**：现有项目只"出题"，几乎没人在"告诉用户该表现哪些侧重点"上做文章（MockMate 有雏形）。这是最锋利的差异点。
2. **拟真追问/压力面（getting the interviewer's intent）**：多数项目是一问一答套路。做成"引用原话深挖 + 判断边界 + 有限度施压"才像真面试官（offerMaster 的追问逻辑可迁）。
3. **可执行的复盘（structured, auditable feedback）**：逐题评分 + 证据引用 + 改进示例 + 雷达图，比"直接问 ChatGPT 拿一段话"更结构化、更可训练。

## 六、成本与展示（支撑 demo 与评分）

- **成本控制**：DeepSeek 主模型 + 本地/免费 TTS + 免费 STT，一场 ≈¥0.3。这样才有胆量做**免费体验**。
- **Demo 前 30 秒 wow moment**：show「上传简历 → 一键生成岗位画像 → AI 面试官开口深挖你简历里的一个点 → 逐题评分报告」，而不是先让你看登录页。
- **素材**：调研记录(已有) + 本调研资料库 + 雷达图/报告截图即可，不必堆量。

## 七、执行顺序（10 小时，按优先级）

1. **0.5h** 定 Memo 骨架 + 技术栈（本文档）。
2. **1h** 最小闭环：选岗位 → 生成画像 → 出 1 题 → 用户打/说答案 → LLM 评分 + 追问。
3. **2h** 接入语音薄层（浏览器 MediaRecorder push-to-talk → 后端 Whisper 转写 → edge-tts 出声）。
4. **1.5h** 追问/压力逻辑 + 逐题评分报告（rubric + 证据 + 改进示例）。
5. **1h** 简历/JD 上传 → 画像 → 出题的串联 + 答题历史（localStorage/本地）。
6. **1h** 复盘页（雷达图 + 弱项训练 + PDF 分享）。
7. **1h** 打磨 UX + 空态 + 加载态 + demo 关键转场。
8. **0.5h** 部署到公网 + 提交物（README/commit 历史/Memo）。
9. 剩余时间做**加分项**：语音流式(可选)、题库扩充、基础性能/安全。

> 更细的代码级参考：offerMaster `agent/nodes.py`+`prompts.py`+`services/voice.py`（语音+追问+评分）、lhw12138 `lib/prompts.ts`+`lib/score.ts`+`lib/question-banks/`（报告+题库）、DeepInterview (prep→live→post 契约)、interview_platform1 `CodeEditor.jsx`+`backend/index.js`（若做写代码加分项）、Piston 客户端封装 `Output.jsx`。
