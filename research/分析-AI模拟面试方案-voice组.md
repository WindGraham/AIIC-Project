# AI 模拟面试方案 · 语音 / LiveKit / 本地 LLM 组分析

> 6 个仓库逐文件取证（README + 配置 + 源码），关键论断均经一手复核。本组涵盖：实时语音 agent（LiveKit 全双工 / 轮询 / 裸 WS 桥）、本地化（本地 STT/TTS/LLM）、苏格拉底式教练。

## 一、逐仓库

### Repo: Assess-AI（Ashmit-Kumar/Assess-AI）
- **GitHub**: see README（README/Task.md/package.json 无仓库 URL；LICENSE "2026 Ashmit Kumar"；Task.md 是客户外包任务书，交付型 contract repo）
- **形式**：video-call-sim —— 浏览器端是真实实时语音面试通话界面（说话/聆听状态 + Monaco 代码编辑器 + 实时字幕面板），但无头像、无摄像头画面，是"模拟视频通话"而非真人视频。
- **目标**：candidate practicing（Task.md 明言 "single-session, stateless-user experience"，无 recruiter 端）。
- **技术栈**：Next.js14+React18+TS+Tailwind v4+@monaco-editor/react+livekit-client（前端）；Express4+TS+Mongoose(MongoDB)+node-redis（后端）；LLM=Groq llama-3.3-70b / llama-3.1-8b（结束评估）；STT=Deepgram nova-2；TTS=Deepgram Aura aura-asteria-en（`.env.example` 却写 ElevenLabs，ElevenLabs 块被注释掉）；agent=Python LiveKit Agents（AgentSession + silero VAD）；realtime=LiveKit WebRTC（字幕 data channel JSON，代码 text-stream topic `'code-update'`）。
- **闭环**：Start → `POST /api/sessions/start`（Redis 状态 TTL 1h）→ `POST /api/livekit/room` 建房+JWT → Python agent 入房加载 MongoDB 题 → VAD→STT→LLM（"Athena" 强制 4 阶段：解释→暴力解→最优解→写码）→TTS → 字幕广播 → 代码 2s 防抖同步给 agent → 结束（`request_end` 或口头 `[[END_INTERVIEW]]`）→ agent 生成 JSON 评估双写 MongoDB+PUT → 结果页 3s 轮询到 evaluated。
- **架构要点**：prompt 驱动的自由式 agent（魔法结束 token）；Redis InterviewState 状态机只被 TS 路径用，Python agent 绕过、直接 pymongo 读题；代码感知靠 `get_latest_code` function tool；评估双实现（agent 内 gpt 路径 vs 后端 evaluationService，输出键不一致）；字幕采集靠 `UserTranscriptLogHandler` 抓 LiveKit SDK 日志（脆弱）。
- **部署/成本**：无 docker；需 MongoDB+Redis+LiveKit Cloud；`npm install`×2+`pip install`，Windows 批处理；env：MONGODB_URI/GROQ_API_KEY/LIVEKIT_*/DEEPGRAM_API_KEY/ELEVENLABS_API_KEY…；成本 Groq 免费层+Deepgram/ElevenLabs 免费额度。
- **亮点**：完整交付 Task.md MVP（实时语音面试+代码编辑器+实时字幕+结构化评估+结果页）；代码实时感知是差异化点；双结束路径+优雅交接；语音优化提示词（"NO Full Stops / 1-3 sentences per turn"）；评估超规格（overallScore A-F、technicalLevel）。
- **不足/差异化机会**：三套 agent 代码并存（Python 线上/TS CLI/278 行全注释版）；.env 与真实 TTS 不符（写 ElevenLabs 用 Deepgram Aura）；字幕不实时持久化（崩溃即丢对话）；评估逻辑双实现、schema 不一致；无鉴权/历史/仪表盘；仅 ~4-5 道种子题、固定 JS 编辑器、英文单语。**机会**：统一单条 agent 管线+通话中实时字幕落库（SSE/WS）；rubric 化+多模型共识评分；鉴权与历史复盘；头像/视频与多语 STT/TTS；候选代码真机测试与自适应难度。
- **可复用**：`agent/agent.py`（LiveKit Python 语音 agent 完整接线,635-660 行 AgentSession 装配）、`backend/src/services/livekit/agent.ts`（TS agent 字幕事件最干净参考）、`frontend/lib/hooks/useLiveKit.ts`（React LiveKit hook）、`backend/src/controllers/livekitController.ts`（建房+候选 JWT+room metadata）、`backend/src/services/evaluation/evaluationService.ts`（Groq JSON 评估+容错）、`backend/src/utils/seedQuestions.ts`（题库种子模式）。

### Repo: interview-ai-assistant（sangh99/interview-ai-assistant）
- **GitHub**: see README（README 只有 `git clone <repository-url>` 占位；LICENSE "2025 LiveKit, Inc."，保留 LiveKit 官方模板痕迹，判断为基于 LiveKit 模板的 hackathon 项目）
- **形式**：voice —— README 首行 "A voice-powered AI interviewer…LiveKit's STT/TTS"；但仓库本身**无任何前端**，需 LiveKit sandbox 或其他前端连房间；README 声称的 `interview_agent.py console` 文本模式实际未实现。
- **目标**：candidate practicing（api/text.md 命题面向"员工 CV 与 JD 不匹配导致面试失败"的内部候选人备试；workflow 对回答打 hire/no_hire，兼具轻度筛查）。
- **技术栈**：后端 Python 双应用——根目录 LiveKit Agents 语音 agent + `api/` Flask-RESTX(Swagger) 简历 CRUD，SQLAlchemy+PostgreSQL；LLM=OpenAI gpt-4o/gpt-4o-mini，嵌入 text-embedding-3-small，OPENAI_BASE_URL 可指 ollama/vllm；STT=Deepgram；TTS=Cartesia；agent=LangGraph StateGraph（9 节点：analyze_inputs→create_interview_plan→start→ask→analyze_answer→decide_follow_up→ask_follow_up/next_question→complete）+ LangChain；realtime=LiveKit WebRTC（AgentSession+Silero VAD+transformer turn-detector MultilingualModel）。
- **闭环**：客户端入房间 → `on_enter()` 用**硬编码 demo 简历+JD** 调 `start_interview()`（RAG 检索+LLM 技能差距分析+按类别从 ChromaDB 取题）→ Cartesia TTS 出题 → 说话 → Deepgram STT 进 `on_user_speech()` → LangGraph `process_answer_and_continue()`（LLM 1-5 打分、决定追问或下一题）→ 完成 → `save_interview_results()` 落 PostgreSQL。
- **架构要点**：三层解耦（语音层↔LangGraph 工作流层↔RAG/持久化层）；ChromaDB 三集合（resumes/job_descriptions/questions）+阈值过滤；全链路 token 省钱设计（resume[:1000] 截断、小模型跑流程）；PostgreSQL 不可用优雅降级；study_planner 双模式（LLM 图模式 vs fast_mode 零 API 正则关键词模式）；`api/` 与语音 agent 无数据打通的独立 Flask-RESTX 应用。
- **部署/成本**：`pip install`→`python setup_and_test.py`→`python interview_agent.py dev`+外部 LiveKit 前端；env：LIVEKIT_*/OPENAI_API_KEY/DEEPGRAM_API_KEY/CARTESIA_API_KEY（可选 TAVILY_API_KEY/DATABASE_URL/OPENAI_MODEL/OPENAI_BASE_URL）；成本全付费 API，LLM 可切本地但语音三件套无法本地化。
- **亮点**：真·端到端语音面试链路（VAD+turn-detector 按场景调参 min_endpointing_delay=0.8）；会话+指标全持久化（InterviewSession/InterviewMetrics 两表）；简历+JD 驱动动态出题；study_planner 双模式（fast 模式零成本降级）；mock_data_generator dataclass 生成多角色简历/JD/题库。
- **不足/差异化机会**：语音 agent 与真实简历/题库完全隔离（on_enter 硬编码 demo）；api/ 与语音 agent 割裂；README 声称的 console 模式未实现；无前端/结果可视化；指标 bug（get_interview_metrics 只读最后一次回答的分析）。**机会**：简历上传→建档→语音面试闭环打通；统一 Web 前端+结果仪表盘；视频/头像面试；行业题库+本地 LLM 成本优化。
- **可复用**：`interview_workflow.py`（LangGraph 面试状态机+token 省钱 prompt）、`rag_system.py`（ChromaDB+PostgreSQL 混合存储、阈值过滤、降级）、`study_planner.py`（双模式学习计划）、`questions.py`（静态分类题库）、`mock_data_generator.py`、`api/app/`（Flask-RESTX 简历 CRUD+Swagger）。

### Repo: warmscreen（wildhash/warmscreen）
- **GitHub**: wildhash/warmscreen（README 克隆 URL 实锤）
- **形式**：text —— 唯一完整打通的端到端闭环是文字 Q&A（文字 transcript 进→打分决策出）；"voice" 层是脚本化单向 TTS 播放+STT 采集+前端轮询字幕，不是可对话的实时语音 agent，也无头像。
- **目标**：both —— 为 recruiter 打造（决策+可解释性+监考+auto-optimize hiring decisions），候选人作被测方；seed.ts 含 RECRUITER 角色。
- **技术栈**：Next.js16(App Router)+React19+Tailwind4+SWR/zustand（前端）；Fastify4+TS+Prisma5+PostgreSQL15+Redis（后端）；**LLM 实际未接入**——agents 全是规则/启发式（analyzer.ts:39 "// Simulate AI analysis"）；openai 声明在 package.json 但全 src 无调用；STT=Deepgram nova-2（live+prerecorded）；TTS=ElevenLabs eleven_multilingual_v2+AGI 声音克隆；agent=自研 7-agent swarm（Analyzer/Verifier/Planner/Tagger/Scorer/Narrator+Conductor）+reflexion 循环（confidence<0.7 重跑、上限 3）+脚本化 VoiceInterviewerAgent；realtime=LiveKit(token/房间)+Fastify WS /api/voice/ws 流式字幕+Deepgram live WS；**前端轮询** transcripts 而非推送。
- **闭环**：recruiter 建面试 → 候选人开始（按 correlationScore/avgScore 取 top-5 题）→ 提交文字答案（Conductor: Analyzer→Tagger→Verifier，全程写 AgentLog）→ finalize → Scorer→Narrator → 落 score/decision/explainability → reflexion.learnFromInterview()+conductor.performSelfHealing()。
- **架构要点**：Turborepo monorepo（apps/{web,api}+packages/{database,agents,shared,voice,proctoring}）；Conductor 编排"每答分析"与"终面评分"两条流水线，AgentLog 审计链；reflexion 是启发式（"refine"=每个分数 +0.5）；"自进化"落 DB（learnFromInterview 更新 Question.timesAsked/avgScore、refineScoringModel 需 ≥5 场、pattern >0.7 存/>0.8 放大）；voice 是 VoiceManager 门面（LiveKit token+Deepgram live STT+ElevenLabs TTS）但"LiveKit agent 集成"只有初始化配置端点写 AgentLog 行，仓库无真实 agent 部署代码；监考每 5s 快照存 proctoringData。
- **部署/成本**：docker-compose(postgres:15+redis:7)→npm install→db:push→db:seed→npm run dev；.daytona.yaml；env 仅 DATABASE_URL 必填；**核心文字闭环零 LLM/API 成本**（agent 全规则化），语音部分按量付费。
- **亮点**：包边界清晰（voice/proctoring/agents 可复用库）；真实落库的学习闭环+完整 AgentLog 审计；输出可解释（DecisionExplanation）；优雅降级（缺 key 503 "Voice service not configured"）。
- **不足/差异化机会**：**全仓库没有一行真实 LLM 调用**——打分是硬编码启发式（technical = hasKeywords ? 7.5 : 5.0），reflexion 是假的（每轮 +0.5），README "7-agent AI recruiter" 严重夸大，这是最大差距点（新产品优势=rubric 化真 LLM 判断）；voice 不可对话；监考是 stub（face-detection.ts 返回硬编码 faceDetected:true）；无鉴权/日程/复核流；Planner agent 在出题路径上没被使用（DB orderBy 替代）。
- **可复用**：`packages/agents/src/orchestrator/conductor.ts`（流水线编排+AgentLog+pattern）、`packages/agents/src/agents/base-agent.ts`（reflexion 抽象）、`packages/voice/src/voice-manager.ts`（LiveKit+Deepgram+ElevenLabs 统一门面）、`packages/proctoring/src/attention-tracker.ts`、`packages/database/prisma/schema.prisma`（Interview/Question/Response/AgentLog/FeedbackLoop/ScoringModel/Pattern 全学习闭环数据模型）、`packages/agents/src/reflexion/learning.ts`、`apps/api/src/routes/interviews.ts`（finalize 端点）。

### Repo: socratic_mirror（krishna684/socratic_mirror）
- **GitHub**: see README（无仓库 URL、无 .git；name "socratic-mirror-agent"，README "built for Gemini hackathon"、MIT）
- **形式**：avatar —— 语音 + Ready Player Me 3D 头像的教练模拟（表情/手势/viseme 口型同步）；无 WebRTC，"视频"只是 1fps JPEG 帧经 WS 喂 Gemini Live 做视觉输入。
- **目标**：candidate practicing —— 三模式（Socratic Tutoring / Interview Prep / Public Speaking）。
- **技术栈**：Next.js(实际 next ^16.1.6+React19)+React Three Fiber/three.js+KaTeX 白板+zustand（前端）；Python3.10+FastAPI+uvicorn+websockets（后端）；LLM=Gemini（免费额度多模型回退 gemini-2.0-flash→2.0-flash-lite→1.5-flash→1.5-flash-8b→2.5-flash，Live 路径另有 gemini-2.5-flash-preview-native-audio-dialog）；STT=浏览器 Web Speech API（Live 路径用 Gemini Live 原生 input_transcription+VAD）；TTS=Google Cloud TTS REST（voice en-US-Neural2-F，SSML <mark> 词级时间戳→viseme）；agent=手写确定性状态机（CoachingEngine+TutorAgentDecisionEngine），无 LangChain；realtime=none（裸 FastAPI WebSocket；上行 PCM16 16kHz base64、下行 PCM 24kHz base64）。
- **闭环**：说话 → AudioProcessor（Web Speech+静音提交）→ `{type:"user_speech"}` 经 /ws/coach/{id} → CoachingEngine.process_text → GeminiClient.generate_structured_response（JSON step/check_in）→ coach_response 回推 → 前端 POST /api/tts → Google TTS 返回 MP3+viseme 事件 → 头像口型同步+白板渲染 → 每 1s biometric_data 进 BargeInDetector（填词/压力/视线）可随时打断。
- **架构要点**：双实时通道（/ws/coach/{id} 回合制；/ws/live/{id} 是 FastAPI WS↔Gemini Live API 双向桥）；Socratic 循环（Gemini 只回结构化 JSON kind: step|check_in、visual.type、avatar_intent），引擎校验 step 单调递增；tutor_agent.py 用正则跟踪困惑/好奇注入行为提示；音频采集 AudioWorklet 降采样→Int16 PCM；头像 RPM .glb+ARKit morph，TTS 词级时间戳→音素启发式→viseme 序列；会话持久化 JSON 文件（5s 防抖落盘、24h 过期、>50 条上下文滑动窗口压缩）。
- **部署/成本**：本地双进程；生产 cloudbuild→Cloud Run（backend --max-instances=1，GEMINI_API_KEY 走 Secret Manager）；env：GEMINI_API_KEY（必）、GOOGLE_TTS_API_KEY（可选，未配 503 降级）、NEXT_PUBLIC_BACKEND_URL、NEXT_PUBLIC_RPM_AVATAR_URL；成本近乎免费（免费额度排序回退，显式避开 gemini-3-* "only 20 req/day on free tier"）。
- **亮点**：真·双实时路径（回合制教练 WS 之外有完整 Gemini Live 桥，原生 barge-in/VAD）；自适应苏格拉底教学（状态驱动困惑计数+行为提示注入）；免费额度友好（429/quota 感知+缓存上次可用模型）；viseme 口型同步管线；生物特征驱动确定性打断规则+LLM 结构化输出+头像意图统一 JSON schema。
- **不足/差异化机会**：**生物特征部分造假**——姿势告警用 Math.random()（5%/5%/5% 概率）、gazeDirection 硬编码 [0,0,0]、@mediapipe/tasks-vision 在依赖但源码零引用；无用户体系/鉴权（allow_origins=["*"]）；JSON 文件存储不可扩展（24h 过期、"摘要"实际是关键词提取占位）；文档-实现漂移（Nano Banana Pro 4K 图、jitter buffer、MediaPipe 均未实现）；面试题目大量模板化+兜底，resume 只是粘贴文本无解析；1fps JPEG 视觉上限。**机会**：真 MediaPipe 视线/姿势/表情识别、用户体系+持久画像、WebRTC 级视频会话、简历解析与个性化追问。
- **可复用**：`backend/tutor_agent.py`（确定性苏格拉底决策引擎）、`backend/gemini_client.py`（配额感知多模型回退+鲁棒 JSON 提取）、`public/audio-capture-worklet.js`（AudioWorklet 降采样→Int16 PCM 采集器）、`src/components/AvatarModel.tsx`（RPM 头像 rig+viseme/能量双路径口型）、`backend/tts_service.py`（SSML <mark> 词级时间戳→viseme）、`backend/live_session.py`（WS↔Gemini Live 双向桥）。

### Repo: grillkit（GrillKit/grillkit）
- **GitHub**: GrillKit/grillkit（README 克隆 URL+ARCHITECTURE.md 实锤）
- **形式**：text —— 核心是打字/语音听写答题；语音是"可选项"（Whisper 听写+Piper 朗读题目+音频作答），听写是缓冲后一次性转录（dictation.py "Buffered PCM audio transcribed on finalize"），**不是实时语音对话**。
- **目标**：candidate practicing —— 自托管单人训练器（"Practice theory Q&A, live coding, or both"），无 recruiter 功能、无账号。
- **技术栈**：服务端渲染 Jinja2 模板+原生 JS+Monaco(CDN)（前端，无 SPA 框架）；FastAPI+SQLAlchemy+SQLite+Alembic 迁移(11 版本)（后端）；LLM=自带 OpenAI 兼容端点（OpenAI/Ollama/vLLM，/config 模型目录管理）；STT=faster-whisper（small/medium/large，本地下载）；TTS=Piper（默认 en_US-lessac-medium ~63MB，本地，WAV 缓存）；agent=无框架（确定性领域层：session phase 状态机、theory/coding section 服务、UoW 分层）；realtime=WebSocket（理论 Q&A 走 WS、coding Submit 走 /coding/ws；无 WebRTC/LiveKit）。
- **闭环**：/config 加 LLM 模型（可下载 Whisper/Piper）→ /setup 选模式（Theory only/Coding only/Theory→Coding/Coding→Theory）+轨道/难度/主题/计时器 → 理论题经 WS 逐题作答、AI 1-5 打分+最多 2 轮追问（≤3 分触发 follow-up）→ 编码题 Monaco 编辑、Run 跑公开测试/Submit 跑隐藏测试（Judge0 CE）+AI 评审 → /interview/{id}/results 总评+分节 review 页（完整对话/代码历史）。
- **架构要点**：会话阶段状态机（SectionKind theory/coding、4 种 session mode）；结构化 JSON 评估（pydantic，1-5 评分 rubric 明确定义+follow_up_needed+MAX_FOLLOW_UP_DEPTH=2）；评估 prompt 自带 STT 错字容忍说明（"typos, misheard words… treat as input errors"）；STT/TTS 协议可替换（SttModelLoader/TtsEngine+in-process runtime）；Judge0 CE（python lang id 71）跑代码、隐藏测试+AI review；known-questions（标记"我会了"并在新会话排除）；YAML 题库（10+ 轨道、junior/middle/senior）；听写=缓冲 PCM 结束时一次性转录。
- **部署/成本**：docker compose up --build（单 app 容器 :8000 + ./data 卷）；编码模式需 --profile coding 起 Judge0（postgres+redis+server+worker，cgroup v1 注意）；env：DATABASE_URL/HF_TOKEN/WHISPER_DEVICE/COMPUTE_TYPE/JUDGE0_URL/AUTH_TOKEN/CODING_MAX_RUNS_PER_TASK；成本 LLM 按提供商（云端 key 或本地 Ollama 免费），Whisper/Piper 全本地。
- **亮点**：六里工程化最完整（Alembic 迁移、mypy strict、ruff、pytest、CHANGELOG、ARCHITECTURE.md 50KB、SECURITY.md）；结构化评分 rubric+追问逻辑+STT 错字容忍是方法论亮点；自托管隐私（"API keys and interview history stay under ./data"）；YAML 题库可编辑扩展；编码任务含隐藏测试+AI 评审+Monaco；dashboard/results/review 页齐全。
- **不足/差异化机会**：单用户无账号；文字优先——无实时语音对话（听写一次性转录，无轮次/打断/实时 ASR 流）；无自适应难度；只支持 OpenAI 兼容一种提供商；编码依赖 Judge0（部署重、cgroup 限制）；服务端渲染原生 JS 偏旧；无简历/JD 个性化。**机会**：实时语音对话（流式 ASR+turn-taking）、多用户与账号/进度云同步、基于作答历史的自适应选题、简历/JD 驱动个性化追问、移动端/PWA。
- **可复用**：`app/theory/domain/evaluator_prompts.py`（1-5 rubric+追问决策+STT 错字容忍）、`app/interview/domain/session_phases.py`（会话阶段状态机、theory/coding 组合）、`app/shared/infrastructure/gateways/judge0.py`+`judge0_config.py`（Judge0 代码执行网关）、`app/shared/infrastructure/gateways/piper.py`+`tts_cache.py`（本地 Piper TTS+WAV 缓存）、`app/ai/faster_whisper_transcriber.py`（faster-whisper 本地转录）、`data/questions/`+`data/coding/`（10+ 轨道×3 级别 YAML 题库）、`app/interview/domain/scoring.py`（完成会话分数解析/聚合）。

### Repo: Seekr（mdjamilkashemporosh/Seekr）
- **GitHub**: see README（无 owner/repo，仅有 user-attachments 图片链接；MIT）
- **形式**：text —— `<textarea placeholder="Type your answer...">` 逐题打字作答，全仓无语音/实时通道。
- **目标**：candidate practicing —— README 首句 "simulates realistic mock interviews to help users practice, prepare, and improve their interview performance"。
- **技术栈**：React19+TS+Vite6+Tailwind4+Zod（前端）；FastAPI+Python3.9（后端）；LLM=本地开源模型 via Ollama+LangChain OllamaLLM（README 支持 Llama 3.3/3.2、Gemma 3、Phi-4、Mistral、DeepSeek）；STT/TTS 无；agent=无（仅两个单轮 REST 端点，无记忆/多轮/工具）；realtime=none（纯 HTTP fetch）。
- **闭环**：选 Topic+Level → GET /questions?topic=&level=&count=20（后端 allowlist 校验后单次 LLM 生成编号列表）→ 前端正则 split(/\n\d+\.\s/) 解析成题目数组 → 逐题 textarea 作答（带进度条）→ Submit → POST /evaluate 把全部 Q1/A1… 拼成一个串单次评估（"满分 100+强弱项总结"）→ cleanEvaluationResult 洗 markdown 展示 → "Start Over" 仅 window.location.reload()。
- **架构要点**：题目生成无结构化约束（prompt 只要求 "Do not include any explanations…"），返回原始文本靠前端正则拆——模型格式漂移即坏；评估批量拼接单次调用，输出自由文本靠正则清洗整体展示；topic/level 后端硬编码 set 校验（60+ 主题含非技术、12 职级），前端 src/data/ 是手工镜像副本有漂移风险；CORS 全开 allow_origins=["*"]；前端硬编码 count=20；无任何持久化。
- **部署/成本**：docker-compose.dev.yml up --build（backend:8000+frontend:5173，配 host.docker.internal:host-gateway 访问宿主机 Ollama）；env 仅 OLLAMA_MODEL/OLLAMA_BASE_URL/VITE_API_BASE_URL；API 费用 $0（本地模型，成本为本地算力）。
- **亮点**：完全本地化+数据不出机器（"Full control and data privacy");12 职级×60+ 主题覆盖面（含产品/市场/销售/HR 等非技术）；架构极简（两个端点、两次提示词模板），换 OLLAMA_MODEL 即可换模型；加载屏轮播 50+ 条面试技巧，等待体验用心。
- **不足/差异化机会**：无多轮对话——20 题一次性生成，不能追问/不能按回答调整；无结构化输出——题目靠正则拆、评估靠正则洗，格式漂移即坏，评估是整段文本无逐题评分/参考答案对比/评分维度；无历史持久化（刷新即失）；纯文本无语音；答案不基于简历/JD、不拦截空答案；README 有复制粘贴残留。**机会**：JSON mode/function-calling 拿结构化题目与逐题 rubrics、多轮动态追问与自适应难度、加 STT/TTS 语音模拟、本地持久化与历史复盘、JD/简历个性化提问。
- **可复用**：`backend/app/config/allowed_topics.py`（60+ 主题白名单）、`backend/app/config/allowed_levels.py`（12 职级白名单）、`backend/app/utils/prompt_builder.py`（system/user 提示词隔离成独立函数）、`frontend/src/utils/parseQuestions.tsx`（LLM 编号列表→题目数组正则解析器）、`frontend/src/utils/cleanEvaluationResult.tsx`（LLM 自由文本 markdown 清理）、`frontend/src/data/interviewTips.tsx`+`shuffleArray.tsx`（加载屏轮播 UX）、`frontend/src/components/QA.tsx`（带进度条线性问答流程）。

## 二、跨项目横向观察（本组）

**实时语音管线四种形态**：
- 全双工真语音（Assess-AI、interview-ai-assistant）：LiveKit 房间+agent 侧 VAD→STT→LLM→TTS 实时对话。体验标杆，但需 LiveKit Cloud+付费 STT/TTS，前端必须写 LiveKit 客户端。
- 半实时/轮询（warmscreen）：LiveKit 只做 token 与房间+Deepgram 流式转写，TTS 是 ElevenLabs REST 返回音频 buffer，前端轮询 transcripts——"voice" 层脚本化单向，无 agent 侧轮次管理。
- 裸 WebSocket+云 Live API（socratic_mirror）：不上 LiveKit，FastAPI WS 桥 Gemini Live（PCM16/24kHz base64 双向），浏览器 Web Speech 兜底——最省钱但延迟/稳定性全押云 API。
- 听写式（grillkit）：STT/TTS 全本地（faster-whisper+Piper），但听写一次性转录，无流式对话；Seekr 完全无语音。

**回合结构**：自由式 prompt（Assess-AI 魔法 token）→ LangGraph 状态机（interview-ai-assistant 9 节点）→ 手写领域状态机（grillkit、socratic_mirror）→ 流水线编排（warmscreen Conductor）→ 批量线性（Seekr）。

**评分/反馈四档**：结构化 rubric（grillkit 1-5+追问+STT 错字容忍；interview-ai-assistant 1-5 四维+hire/no_hire）→ 结构化 JSON 但 schema 不一致（Assess-AI）→ 加权规则打分+招聘决策（warmscreen 全启发式无 LLM）→ 自由文本（Seekr、socratic_mirror 教练风格）。

**LLM 策略**：付费云（Groq/OpenAI/Gemini 免费额度回退）→ 可替换/自托管（grillkit OpenAI 兼容端点）→ 纯本地（Seekr Ollama 零 API 费）→ **根本没有 LLM**（warmscreen 规则启发式，最大"包装 vs 现实"反差）。

**工程完整度**：grillkit（迁移/mypy/测试/文档齐全）> Assess-AI（能跑通 MVP 但债重）> warmscreen（架构漂亮但核心未实现）> socratic_mirror（demo 惊艳有假组件）> interview-ai-assistant（链路真但没接真实数据、无 UI）> Seekr（玩具级但零成本）。

**通用机会窗口**：① 真 LLM 判断+rubric 化评分（warmscreen 缺口）；② 通话中实时字幕/结果持久化（Assess-AI 崩溃丢数据）；③ 简历/JD→个性化面试闭环（interview-ai-assistant 硬编码 demo、grillkit/Seekr 完全无个性化）；④ 真视觉分析（socratic_mirror 假生物特征）；⑤ 实时流式语音对话+多用户账号；⑥ 结构化输出约束（JSON mode）取代正则解析（Seekr/Assess-AI 脆弱点）。
