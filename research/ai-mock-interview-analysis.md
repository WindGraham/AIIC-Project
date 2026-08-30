# AI Mock-Interview Repos — 结构化分析

基于 `/root/AIIC-Project/research/ai-mock-interview/` 下六个仓库的实际文件阅读（README / requirements.txt / package.json / docker-compose.yml / .env.example / app·src·components·agent 源码），所有结论均来自磁盘上的真实代码。

---

### Repo: ai-interviewer

- **GitHub**: see README — README 未给出仓库 URL，目录内无独立 `.git`（`git remote` 指向父级 AIIC-Project）。自述 credits FastAPI/aiortc/Whisper/OpenRouter/Coqui。
- **形式 (interaction form)**: **voice** — 浏览器麦克风通过 WebRTC 推流到 aiortc 服务端，静音分段后走 STT→LLM→TTS 再经同一 WebRTC 回传语音；页面虽有 "Your Camera" 视频框，但服务端 `VideoPassthrough` 只是把视频原样回环，无任何 AI 视觉。
- **目标用户**: candidate practicing（README: "Practice your interview skills"）。
- **技术栈**:
  - frontend: 原生 HTML/CSS/JS 单页（`index.html`），`getUserMedia` + 手写 RTCPeerConnection
  - backend: FastAPI + uvicorn + aiortc（Python 3.9+）
  - LLM: OpenRouter API（`AsyncOpenAI` client，默认 `openai/gpt-3.5-turbo`，base_url 指向 OpenRouter）
  - STT: faster-whisper 本地模型（默认 `base`/CPU/int8，首次运行需下载）
  - TTS: gTTS + pydub（mp3→wav 转换）；README 声称 Coqui TTS，**实际代码是 gTTS**（文档与代码漂移）
  - agent-orchestration: 无 — 单一线性 pipeline，无 agent 框架
  - realtime: **WebRTC**（aiortc 服务端 + Google STUN）
- **核心功能闭环 (MVP loop)**: 浏览器 `getUserMedia` 麦克风 → POST `/offer` 交换 SDP → 服务端 `AudioProcessor` 累积音频直到 2 秒静音 → faster-whisper 转写 → OpenRouter LLM（带会话历史、system prompt 限定 interviewer role）→ gTTS 合成 → 切成 20ms frame 塞进 `response_queue` 经 WebRTC 播放；连接稳定约 1 秒后自动发问候语开场。
- **架构要点**: 每个 peer 一个 `AudioProcessor(MediaStreamTrack)`，`recv()` 里先吐队列中的 TTS 响应帧、再消费用户帧并返回静音帧（避免回声）；能量 RMS 阈值 (0.01) 检测说话/静音，静音 ≥2s 且缓冲 ≥1s 触发整段处理；顺带采集 voice stats（音量均值/峰值、clarity_score、说话时长）；`llm.py`/`stt.py`/`tts.py` 都是可替换的全局单例。
- **部署/成本**: `docker-compose.yml`（build . → 8000 端口 + healthcheck）或直接 `uvicorn app.main:app`；`.env.example` 只需 `OPENROUTER_API_KEY`；成本 = OpenRouter token 费用（gTTS 免费、Whisper 本地免费），GPU 可选加速。
- **亮点**: 六仓库中唯一真正"自托管 WebRTC 语音回路"（aiortc 服务端 + 本地 Whisper）；静音门控 + 响应帧队列实现得很干净；stt/llm/tts 三模块单例化便于换实现；附带实时 voice stats 接口 `/stats/{peer_id}`。
- **不足 / 差异化机会**: 会话历史是**全局单例**，多 peer 共用一份（`/reset/{peer_id}` 也重置全局），多用户即串场；README 与代码多处漂移（Coqui→gTTS、根目录 `app.py` 是一个与 `app/main.py` 无关的残缺 WebSocket 骨架）；无打断(barge-in)、无流式 TTS、无评分/总结（README Future 清单自认）；gTTS 延迟高且音色机械。新产品机会：按 peer 隔离会话、加打断与流式 TTS、结束时结构化评分、把无意义的 video passthrough 换成真头像。
- **可复用模块**:
  - `app/webrtc_handler.py` → 静音门控的 WebRTC 音频回路 + 20ms 帧队列（语音产品可直接借鉴）
  - `app/llm.py` → OpenRouter 接入 + interviewer system prompt（角色化提问模板）
  - `app/stt.py` → faster-whisper 异步封装（模型可配置）
  - `index.html` → 手写 WebRTC 客户端 JS（offer/answer + remote audio 播放）

---

### Repo: Ai-Video-Interviewer

- **GitHub**: see README — clone URL 是占位符 `your-username/ai-video-interviewer`。
- **形式 (interaction form)**: **video-call-sim** — 页面呈现视频通话式界面（本地摄像头 + 一个静态 AI 图片 `ai_visual.png`），但"AI 侧"没有视频、没有真头像，交互是 push-to-talk 录音的回合制语音。
- **目标用户**: candidate practicing（README 明言 "mock interview platform…helps users practice"）。
- **技术栈**:
  - frontend: HTML/CSS/JS（`templates/index.html` + `static/script.js`），`getUserMedia` 摄像头预览 + MediaRecorder 录音
  - backend: Flask + Flask-Cors（单文件 `app.py`）
  - LLM: **Hugging Face Space `ahmedatk/ai_interviewer`** 经 `gradio_client` 调用（第三方托管 Space，`/gradio_start_interview` 与 `/gradio_handle_response` 两个 API）
  - STT: `SpeechRecognition.recognize_google`（Google 免费 Web Speech API）
  - TTS: gTTS → mp3 存到 `static/audio/` 由前端 `<audio>` 播放（需 FFmpeg）
  - agent-orchestration: 无 — 会话历史是前后端来回传递的**一个字符串**
  - realtime: none（HTTP multipart 上传，回合制）
- **核心功能闭环 (MVP loop)**: 上传简历 PDF + 粘贴 JD → POST `/start-interview` → gradio_client 调 HF Space 生成整段开场对话 → 取最后一行当第一问 → gTTS 出 mp3 → 用户点 Record 说话、Stop 上传 webm → pydub 转 wav → Google STT 转写 → HF Space `/gradio_handle_response` 返回新一段对话 → 用 `split(user_response_text,1)[-1]` 字符串手术截出 AI 新回答 → 再 TTS 播放，聊天气泡更新。
- **架构要点**: 状态全部寄存在 HF Space（Space 内部记住简历/JD 上下文），本地服务端无状态；对话以 markdown 风格纯字符串累积并在前端按 `\n` 分行渲染；FFmpeg 路径**硬编码 Windows `C:\ffmpeg\bin`**；启动时连不上 HF Space 直接 `sys.exit(1)`。
- **部署/成本**: `pip install Flask Flask-Cors gradio_client gTTS SpeechRecognition pydub`（**仓库没有提交 requirements.txt**）+ 系统 FFmpeg；前端硬编码 `http://127.0.0.1:5001`；成本≈0（HF 免费 Space、Google STT 免费、gTTS 免费），但完全依赖一个不属于自己的第三方 Space 在线。
- **亮点**: 简历 + 职位描述个性化问题真正跑通了端到端（借道 HF Space）；聊天 UI 简洁；代码量最小、易读懂。
- **不足 / 差异化机会**: "Video Interviewer" 名不副实（无 AI 视频/头像）；脑是别人的 HF Space（离线即死，README 自认是风险）；字符串切片维护对话极易碎；Windows 硬编码 FFmpeg 路径；Google STT 失败无兜底；无评分/反馈；视频从未上传。新产品机会：换成自有 LLM 后端 + 真头像 + 实时传输 + 结构化会话存储，或把这个"异步录音应答"形态正名为异步视频初筛（HireVue 式）。
- **可复用模块**:
  - `app.py` 的 `text_to_speech()` → 时间戳 mp3 落盘 + URL 返回的轻量 TTS 辅助函数
  - `static/script.js` → Record/Stop → webm 上传 → 气泡渲染的录音应答交互流
  - `app.py` 的 pydub webm→wav 转换片段 → 服务端音频格式归一化

---

### Repo: AI-agent-Avatar-Interview-Assistant

- **GitHub**: weg-9000 / Multi-agent-AI-Avatar-Interview-Assistant（由 README 内图片 URL 推断）。
- **形式 (interaction form)**: **avatar** — 前端用 `SpeechSDK.AvatarSynthesizer` 起 Azure AI Avatar（角色 "Meg"、business 风格）经 WebRTC relay 输出口型同步视频；用户可用文字或浏览器语音（webkitSpeechRecognition, ko-KR）作答。
- **目标用户**: candidate practicing（简历输入 → 公司调研 → 模拟面试 → 评估报告 → 导出）。
- **技术栈**:
  - frontend: React 18 + React Router + react-markdown；`microsoft-cognitiveservices-speech-sdk`（AvatarSynthesizer 客户端直连 Azure TTS relay）；axios
  - backend: FastAPI + pydantic-settings；`azure-cosmos`（Cosmos DB，repository 分层）；**Semantic Kernel 1.28**（ChatCompletionAgent）
  - LLM: **Perplexity API**（`AsyncOpenAI` 指向 `PERPLEXITY_ENDPOINT`，经 SK 的 `OpenAIChatCompletion` + 自定义 async_client）；`azure-ai-formrecognizer` 在 requirements 里但代码未见使用
  - STT: 浏览器 Web Speech API（客户端，非服务器）
  - TTS: Azure Speech（SSML，`ko-KR-SunHiNeural`）
  - agent-orchestration: Semantic Kernel 三个 ChatCompletionAgent（CompanyResearch / InterviewQuestion / Evaluation）**顺序调用**，Cosmos 当共享内存
  - realtime: **WebRTC**（仅客户端↔Azure TTS relay 的 avatar 通道），其余 REST
- **核心功能闭环 (MVP loop)**: 用户输入 markdown 简历 + 公司 + 职位 → POST `/api/interviews/research`（CompanyResearchAgent 写 `talentIdeal` 到 Cosmos）→ POST `/generate-questions`（InterviewQuestionAgent 融合简历+人才画像，正则解析出 3 个问题）→ `AvatarComponent` 起 Azure avatar WebRTC 会话、用 SSML 逐题朗读 → 用户 90 秒计时内文字或语音作答（语音经 `useSpeechRecognition` 转文本）→ POST `/save-response` → POST `/api/evaluations/...`（EvaluationAgent 按 5 维度批量评估）→ ResultsPage markdown 渲染 + 导出 .txt。
- **架构要点**: "multi-agent" 实为三阶段串行 pipeline，靠 Cosmos（resume/talent/question/response/evaluation 五张 repo）做阶段间数据传递；公司画像按 `company_name` slug 缓存；avatar = Azure 官方 AvatarSynthesizer + `/cognitiveservices/avatar/relay/token/v1` 取 ICE；全部提示词/UI 为韩语；问题解析靠 `^\s*\d+\.` 正则。
- **部署/成本**: `docker-compose.yml` 编排 backend(:8000) + frontend(nginx :80)；环境变量需 Cosmos、Perplexity、Speech、Document Intelligence 全套（**无提交 .env.example**，README 列了变量）；成本是六仓库里最高的实打实云账单：Azure Avatar/TTS 分钟数 + Perplexity token + Cosmos。
- **亮点**: 最接近"产品"的形态 — 真动画头像 + 口型同步、公司调研个性化、结构化 3 问、五维评估 + 改进建议、用户/简历/结果持久化、结果导出；架构分层（agents/api/core/db/services）最规范。
- **不足 / 差异化机会**: **没有追问闭环** — 头像只会读预先生成的 3 个问题，缺少逐答对话的 Interviewer Agent（README 声称语音识别"previously supported"，但代码仍保留 speech 模式，文档漂移）；评估是全部答完后的**一次性批处理**，无逐题评分；Perplexity 当通用 chat LLM 用属非常规（贵且慢）；FormRecognizer 未接线；韩语硬编码。新产品机会：补一个逐轮追问的对话 agent、逐题 rubric 评分、多语言、用 2D 口型头像替代 Azure 高昂的 Avatar 分钟费。
- **可复用模块**:
  - `frontend/src/components/Avatar/AvatarComponent.js` → Azure Avatar 完整接入（ICE relay token 获取、RTCPeerConnection、SSML 朗读、生命周期）
  - `Backend/app/agents/evaluation_agent.py` → 五维面试评估提示词模板（相关性/专业性/沟通/解决问题/公司匹配）
  - `Backend/app/agents/interview_question_agent.py` → SK ChatCompletionAgent + repository 落库范式
  - `Backend/app/db/repositories/*.py` → Cosmos repository 分层写法

---

### Repo: ai_mock_interview

- **GitHub**: see README — clone URL 是占位符 `yourusername/ai-mock-interview`；README 自述受一个 YouTube AI Interviewer 教程启发。
- **形式 (interaction form)**: **voice** — `@vapi-ai/web` 发起 VAPI 实时语音通话（类电话会议 UI + 实时转写条），无视频/头像。
- **目标用户**: candidate practicing — 但带"社区共享题库"味道（首页 "Take an Interview" 展示其他用户 finalized 的面试）。
- **技术栈**:
  - frontend: Next.js 15 (App Router/Turbopack) + React 19 + TypeScript + Tailwind v4 + shadcn/ui；`@vapi-ai/web`
  - backend: Next.js API routes + **Firebase Admin SDK**（Firestore + Firebase Auth）
  - LLM: 提问用 **Gemini 2.0 Flash**（Vercel AI SDK `generateText`），反馈用 `generateObject` + Zod schema；**通话内 LLM 是 VAPI 里的 GPT-4**
  - STT/TTS: 都在 VAPI 内 — transcriber Deepgram `nova-2`，voice ElevenLabs `sarah`（`constants/index.ts` 的 `interviewer: CreateAssistantDTO`）
  - agent-orchestration: 无 — VAPI 工作流/assistant 配置 + Gemini 旁路调用
  - realtime: **VAPI**（`@vapi-ai/web` 封装 WebRTC）
- **核心功能闭环 (MVP loop)**: 注册登录 → `/interview` 生成页填 role/level/techstack/type/amount → POST `/api/vapi/generate` → Gemini `generateText` 返回 JSON 问题数组（提示词专门要求去掉会破坏语音助手的字符）→ 存 Firestore（`finalized: true`）→ `/interview/[id]` 页 `Agent` 组件用 `vapi.start(interviewer, {variableValues:{questions}})` 把问题注入 assistant system prompt → 实时语音对话（`vapi.on('message')` 只收 final transcript 存 messages）→ 挂断 → server action `createFeedback`：Gemini `generateObject(feedbackSchema)` 产出总分 + 5 维分 + strengths/improvements/finalAssessment → 存 feedback 集合 → `/feedback` 页。
- **架构要点**: VAPI 一肩挑 STT/LLM/TTS/打断检测，应用只做"题面生成 + 事后结构化反馈"两件外围事；Zod `feedbackSchema` 用字面量限定 5 个维度名，保证 Gemini 输出可被 TS 安全消费；`getLatestInterviews` 公开拉取他人 finalized 面试形成"公共练习池"；面试封面随机取品牌图。
- **部署/成本**: `npm run dev`（Vercel 友好）；env 需 Firebase 客户端+Admin、`NEXT_PUBLIC_VAPI_WEB_TOKEN`、`NEXT_PUBLIC_VAPI_WORKFLOW_ID`（**该 workflow 必须自己在 VAPI 控制台建，仓库只含面试型 assistant 配置**）、Gemini key；成本 = VAPI 按分钟（Deepgram+ElevenLabs+GPT-4）+ Gemini；无 docker。
- **亮点**: 六仓库中产品闭环最完整（认证 → 生成 → 语音面试 → 结构化反馈 → 历史记录）；反馈 schema 结构化程度最高（5 维打分 + 点评）；`interviewer` DTO 是一份可读的 VAPI assistant 配置，改音色/提示词零成本；公开练习池是差异化雏形。
- **不足 / 差异化机会**: 语音全押 VAPI 付费 SaaS 且依赖外部 workflow id；反馈只基于文本转写（无语音质量/语速/停顿指标）；问题生成后固定（VAPI 模型虽可自由追问，但无难度自适应编排）；无简历输入；**"Your Interview" vs "Take an Interview" 混排把"个人练习"和"他人面试公开池/筛选内容"两种心智混在一起**（详见横向观察）。新产品机会：加简历 grounding、按答错率动态出题、语音韵律指标、把练习与筛选场景明确分层。
- **可复用模块**:
  - `components/Agent.tsx` → VAPI 调用生命周期 + transcript 采集 + 挂断触发反馈的完整范式
  - `constants/index.ts` → `interviewer` VAPI DTO + `feedbackSchema`（Zod 结构化反馈契约）
  - `lib/actions/general.action.ts` 的 `createFeedback` → Gemini `generateObject` → Firestore 落库
  - `app/api/vapi/generate/route.ts` → 面向语音朗读的题目生成提示词（禁特殊字符、要求 JSON 数组）

---

### Repo: InterviewPal

- **GitHub**: see README — 无仓库 URL（hackathon 项目，README 只给 YouTube 演示链接）。
- **形式 (interaction form)**: **voice** — 浏览器直连 OpenAI Realtime API 的实时语音对话（always_listen 打断、noise reduction），无视频/头像。
- **目标用户**: candidate practicing（README 明确面向学生/职场新人）。
- **技术栈**:
  - frontend: React 19 + Redux Toolkit + Vite；**不用 SDK，手写 `RTCPeerConnection` + `oai-events` data channel** 直连 `api.openai.com/v1/realtime/calls`；axios + supabase-js
  - backend: FastAPI + httpx；LangChain `create_agent`（工具：`fetch_job_desc` 查 Supabase `roles` 表、`prepare_questions`）；pypdf 解析 PDF
  - LLM: 通话内 **OpenAI Realtime `gpt-realtime`**（voice=alloy）；题面/简历解析用 gpt-3.5-turbo（`init_chat_model`）
  - STT/TTS: 内置于 OpenAI Realtime 模型（原生）
  - agent-orchestration: LangChain tool-calling agent 只用于题面准备；面试本身由前端 data channel 事件驱动
  - realtime: **WebRTC → OpenAI Realtime API**（后端 `/interview/token` 发 ephemeral client secret；另有旧版 `/interview/session` 做 SDP 转发）
- **核心功能闭环 (MVP loop)**: Onboarding 选 role+company → 后端 `fetch_job_desc` 从 Supabase `roles` 表取 JD → 上传简历 PDF → `/resume/context`（pypdf 提文本 → `parsed_resume` 提示词出结构化 JSON）→ `/question/` → LangChain agent 调 `prepare_questions` 工具 → 4 类问题（简历/技术/行为/公司，各 1 题，JSON）→ InterviewPage → `ConvoAI`：GET `/interview/token` 换 ephemeral key → WebRTC 建连 → data channel 发 `session.update`（always_listen、interrupt_response、near_field 降噪）→ 注入含问题的 system item → `response.create` 开场 → 用户语音作答、AI 实时问答（`input_audio_buffer.processed` 事件自动触发 `response.create`）→ Stop 结束。
- **架构要点**: 语音全栈都在 OpenAI Realtime 一个模型里（无独立 STT/TTS/LLM 组件）；ephemeral client secret 让浏览器持短期令牌而 API key 留在服务端；题目提前用 LangChain 工具调用生成，通话中靠模型自身自然追问；后端 `interview_agent.py` 只是 sounddevice 录音回放的**占位 stub**，`interview_service.py`、`evaluation_service.py` 均为**空文件**（README "Next Steps" 自认评估未做）。
- **部署/成本**: 无 requirements.txt、无 docker、无 .env.example；需要 `REALTIME_API_KEY`（OpenAI）+ `SUPABASE_URL/KEY` 且 roles 表要手动填充数据；成本 = gpt-realtime 音频分钟（贵）+ gpt-3.5-turbo token；README 自述**因 API 额度没部署**。
- **亮点**: 手写 OpenAI Realtime WebRTC 的接入样板最完整（ephemeral token 端点 + data channel session 配置 + 处理完输入自动触发响应）；支持打断的真实时语音；简历+JD 双 grounding 的出题链路（LangChain tools）清晰；24 小时 hackathon 产出。
- **不足 / 差异化机会**: 后端一半是空壳（interview/evaluation 全空）；会话/转写无持久化；题目预生成、无动态难度调整（Realtime 模型可追问但无编排）；无任何反馈/评分（evaluation_service 空）；依赖手工灌数据的 Supabase roles 表；成本不可持续。新产品机会：补转写落库 + 结构化评估（可照抄 ai_mock_interview 的 Gemini 反馈范式）、把 4 类题的 JSON 契约转成动态题库、用更便宜的语音栈替代 gpt-realtime。
- **可复用模块**:
  - `frontend/interviewpal/components/ConvoAI/ConvoAI.jsx` → 原始 OpenAI Realtime WebRTC 客户端范式（ephemeral token、session.update、always_listen、自动 response.create）
  - `backend/app/api/v1/routes/interview.py` → ephemeral token / SDP 转发端点写法
  - `backend/app/agents/question/tools.py` 的 `prepare_questions` → 四类问题 JSON 生成提示词（可当题库契约）
  - `backend/app/agents/resume/resume_agent.py` → 简历→结构化 JSON 的解析提示词

---

### Repo: intervio

- **GitHub**: see README — 无仓库 URL。
- **形式 (interaction form)**: **text** — 纯文本聊天 UI（React chat + SSE 流式），全仓无任何音频/视频代码。
- **目标用户**: candidate practicing（个人化面试教练，跨会话记忆）。
- **技术栈**:
  - frontend: React 18 + Vite + TS，零 UI 依赖的简洁 chat/sidebar/profile/memories 界面
  - backend: FastAPI + LangChain + **LangGraph**；SQLite（FTS5 全文索引 + 自研本地哈希 embedding）
  - LLM: **DeepSeek**（`deepseek-chat`，经 langchain-openai `ChatOpenAI` + `base_url` 指向 `https://api.deepseek.com`）
  - STT/TTS: 无
  - agent-orchestration: LangGraph 状态图（`retrieve_memories → interviewer → END`）+ 每轮后的 LLM 记忆蒸馏
  - realtime: none（HTTP POST + SSE `token/memories/facts_saved/done` 事件流）
- **核心功能闭环 (MVP loop)**: ProfileModal 填目标角色/公司 → 聊天：POST `/api/chat/stream` → 图先 `retrieve_memories`（hybrid search：FTS5 BM25 + 本地 embedding 余弦，RRF 合并 + 按天指数衰减）→ `interviewer` 节点把 profile+top-K 记忆+轮数拼进 system prompt → DeepSeek 一次一问、按 STAR 追问 → 每轮结束后蒸馏 LLM（`distillation.py`）从问答中抽取持久事实 → 写成 Markdown 文件（`data/memories/*.md`，源数据）并建 SQLite 索引 → MemoriesDrawer 可浏览/删改；会话存 SQLite session store。
- **架构要点**: "本地优先记忆"是灵魂 — Markdown 文件是唯一事实源、SQLite 只做索引（FTS5 + per-row embedding），可审计/可版本化；蒸馏保持记忆精炼（只存 durable facts，忽略寒暄）；`HashingEmbedder` 是零依赖的弱 embedding（README 明说可换 sentence-transformers）；单用户无认证；附带 `openclaw/`（一个 WhatsApp agent skill 复用同一套 coach 提示词）。
- **部署/成本**: `pip install -r requirements.txt` + 复制 `backend/.env.example` 填 `DEEPSEEK_API_KEY`；`uvicorn app.main:app` + `npm run dev`（vite 代理 :8000）；成本仅 DeepSeek token（极低）；无 docker、无云服务。
- **亮点**: 记忆架构在六仓库中独一份（跨会话个性化 + 可读 Markdown + 混合检索 + 时衰 + LLM 蒸馏）；`prompts.py` 的 interviewer system prompt 是面试行为规范写得最好的（一次一问、STAR、难度自适应、逐题反馈）；LangGraph 图极简清晰；隐私友好、部署成本趋近零。
- **不足 / 差异化机会**: 纯文本 — 真实面试是口语，缺语音形态与语音指标；无会话结束的结构化打分/报告（反馈是聊天内自由形式）；弱 embedding 拖累检索（README 自认）；单用户无账号体系；没有题库/rubric，完全靠提示词驱动。新产品机会：把记忆层搬到语音产品里（跨会话记住候选人口语素材），补语音模态 + 逐题评分 + 结课报告。
- **可复用模块**:
  - `backend/app/memory/store.py` → 本地优先混合检索记忆库（Markdown 源 + FTS5 + embedding + RRF + 指数衰减）
  - `backend/app/memory/distillation.py` → LLM 记忆蒸馏提示词与解析（JSON 事实抽取）
  - `backend/app/agent/prompts.py` → 面试教练 system prompt（行为规范可直接移植）
  - `backend/app/api/chat.py` → SSE 流式对话端点（token/memories/facts_saved 事件设计）

---

## 跨项目横向观察

**第三方语音 SaaS vs 自托管：**

- **重度依赖第三方语音 SaaS**：`ai_mock_interview`（VAPI 一肩挑 Deepgram STT + ElevenLabs TTS + GPT-4，连 workflow 都要在 VAPI 控制台建）、`InterviewPal`（OpenAI Realtime 一个模型包办 STT+LLM+TTS）、`AI-agent-Avatar-Interview-Assistant`（Azure Speech/Avatar 负责头像+TTS，浏览器 STT）。这三家是"付费按分钟/按 token 买语音闭环"，启动最快但成本与供应商锁定最重。
- **自托管/半自托管**：`ai-interviewer` 是唯一真正本地语音栈（aiortc 服务端 WebRTC + faster-whisper 本地 STT），但 TTS 用的是免费云 gTTS，README 声称的 Coqui 并未落地；`Ai-Video-Interviewer` 管线自建但 STT（Google Web Speech）、TTS（gTTS）、LLM（HF Space）全是第三方免费云。`intervio` 干脆没有语音（纯文本 + DeepSeek，成本最低）。
- 结论：**语音质量/实时性 → 买 SaaS（VAPI/Realtime/Azure）；成本/自控 → 本地 Whisper + 免费云 TTS；中间地带（可投入产品化的）目前是空白** —— 没有一家把自托管 STT + 流式/克隆 TTS + 本地图编排组合成稳定产品。

**"候选人练习" vs "招聘方筛选"的混淆：**

- 六仓库**全部**面向 candidate practicing，没有一个是真正的招聘筛选工具。
- 混淆最明显的是 `ai_mock_interview`：首页把"我练习过的问题"和"别人的 finalized 面试"混在同一个 "Take an Interview" 公共池里，且带面试评分，形态上像练习又像筛选内容市场 —— 练习者心流（低压力、可重来）与筛选心智（被评估、一次性）被糅在一起。
- `Ai-Video-Interviewer` 自称"real-time video call simulation"，实现却是**异步录答-应答**（Record → upload → AI 回复），这正是 HireVue 式异步视频初筛的交互形态 —— 用筛选工具的交互做练习产品，语义打架。
- `AI-agent-Avatar-Interview-Assistant` 的评估维度含"公司匹配度"、数据模型里有 `talent`（人才画像）repository，是招聘方语言搬进练习场景；其 90 秒限时作答也更像筛选压力测试而非练习。
- `ai-interviewer` / `InterviewPal` / `intervio` 则纯粹是候选人侧，无此混淆。
- 对新产品：**"练习态"（可暂停、可重答、有教练反馈、无后果）与"模拟评估态"（限时、计分、一次性、模拟真实筛选压力）应作为两个显式模式分离设计** —— 目前六个仓库全部默认只做练习态，同时又在 UI/交互上无意泄露筛选态元素，这正是差异化切口。
