# AI 模拟面试方案 & 面试工具 · 新增 6 仓库分析（经 mihomo 代理成功拉取后）

> 这 6 个仓库此前因网络未能克隆、仅有 README；部署 mihomo 代理后成功拉取，现做逐文件代码级分析。
> Group A = AI 模拟面试（4），Group B = 面试视频/编码工具（2）。

## Group A — AI 模拟面试

### Repo: AI-Interview（HopeLoom/AI-Interview）
- **GitHub**: HopeLoom/AI-Interview。
- **形式**: video-call-sim —— 面试页有 VideoParticipant 视频磁贴（`useCameraStream.ts` 调 getUserMedia 显示候选人本人摄像头）+ LiveCodingLayout + WebSocket 聊天；面试官侧为 AI 生成的 panelist 图+文字，非真实多方 WebRTC。
- **目标**: both —— 单代码库三模式：candidate-practice（练习）、company-interviewing（HR 筛选）、company-candidate-interview（凭邀请码免注册面试）。
- **技术栈**: React18+TS+Vite+Tailwind+shadcn/ui+wouter；FastAPI+Python；多 LLM（OpenAI/DeepSeek/Gemini/Grok/Groq/Perplexity）；STT/TTS（OpenAI/ElevenLabs/Google/Groq）；agent 编排（master+panelist+activity+evaluation_agent，队列异步、WebSocket）；SQLite/Postgres/Firebase + Chroma 向量记忆。
- **闭环**: 公司填 JD+上传简历 → `interview_configuration/service.py::generate_full_configuration` 7 步流水线（JD→job_details→coding activity+starter code→panelist 人设→简历解析→候选画像→master config）→ 候选人凭邀请码进入 → WebSocket 面试（master 路由 panelist/activity agent）→ evaluation agent 逐 topic 评分 → 报告。
- **架构要点**: master agent 集中编排、消息队列解耦；panelist 流程 Think→Domain Knowledge→Respond→Reflect→Evaluate；角色/召回/图记忆（Chroma）；逐 topic criteria 评分；Vite 三套构建。
- **部署/成本**: uvicorn 于 GCP VM（README 有 e2-standard-4+nginx+certbot）；env OPENAI_API_KEY 等 + backend/config.yaml；注意 README 称 `cp .env.example .env` 但仓库无该文件。成本高：多 agent 多次 LLM 调用 + 每次配置生 panelist 头像。
- **亮点/不足**: 多 agent 拟真面试团（含编程行为监控）；JD+简历→完整配置自动化；多 LLM fallback。不足：自述 prototype（认证简化）、录制/转录等 README 超出代码、单次配置成本高、示例数据硬编码。
- **可复用**: `backend/interview_configuration/service.py`（JD+简历→配置流水线）、`backend/master_agent/master.py`、`backend/evaluation_agent/evaluation.py`（criteria 评分）、`backend/panelist_factory/`（面试官人设生成）、`backend/core/prompting/prompt_strategies/`、`backend/utils/resume_file_reader.py`、`client/src/components/configuration/`。

### Repo: NextStep.AI（fabio-pecora/NextStep.AI）
- **GitHub**: fabio-pecora/NextStep.AI（用户提供；README 为占位 clone URL）。
- **形式**: voice+text+avatar —— 浏览器录音（Whisper 转写）+ 文本；`mock_interview.html` 静态 PNG 头像帧（blink/mouth_open/listen）由 JS 切换模拟"说话"；TTS 走 gpt-4o-mini-tts。无实时视频。
- **目标**: candidate practicing（150+ 学生，个人备考闭环）。
- **技术栈**: Flask+SQLAlchemy+Postgres(Supabase)；OpenAI GPT+Whisper STT+gpt-4o-mini-tts；Jinja+原生 JS；PyPDF2；xhtml2pdf。
- **闭环**: 注册 → 答每日/角色题（文本或语音）→ LLM 结构化评分（relevance/confidence/final 分数+优缺点+STAR/精简改写）→ 入库 → 个人页趋势/streak → 每日最佳答案上排行榜。
- **架构要点**: 严格 JSON schema+校验（utils/evaluation.py）；简历 grounded 备考报告（resume 为真源，"experience_source_quote" 逐条引用证明，防泛化——utils/prep_generator.py）；JD+公司+简历→定制 prep plan；ATS 简历分析；winners 每日评选+排行榜；64KB app.py 单体。
- **部署/成本**: `python app.py`；env OPENAI_API_KEY/DATABASE_URL/FLASK_SECRET_KEY；gunicorn；纯 OpenAI 按 token 计费。
- **亮点/不足**: Practice→Evaluate→Improve→Track→Repeat 闭环完整；结构化打分+改写；简历锚定防泛化；游戏化（streak/排行榜）。不足：无多轮追问引擎、头像贴图、单一 LLM、题库静态 JSON、单体难扩展。
- **可复用**: `utils/evaluation.py`（评分提示+schema）、`utils/prep_generator.py`（简历+JD→带引用的结构化报告）、`utils/resume_review_generator.py`（ATS 分析）、app.py 的 streak/winners 逻辑、`templates/mock_interview.html`（头像状态机）、`data/*.json`（题库）。

### Repo: MockMate（linghuashenli65-bit/MockMate）
- **GitHub**: linghuashenli65-bit/MockMate（用户提供；README 无 URL）。
- **形式**: voice —— 双向实时语音（WebSocket 流式 ASR + CosyVoice 流式 TTS），多面试官切换；另有文本输入。无视频。
- **目标**: candidate practicing（支持匿名共享 Key 模式与登录 BYOK）。
- **技术栈**: Vue3+Vite+Pinia；FastAPI+uvicorn；LLM 四厂商 MiMo/DeepSeek/Qwen/智谱统一客户端+fallback（backend/ai_client.py）；STT frontend-vue/src/services/asr.js（FSM+噪声门）；TTS backend/cosyvoice_ws.py（DashScope CosyVoice v3.5-flash）+MiMo TTS；MySQL/JSON 双持久化；5 层安全；backend/finetune/ LoRA 微调。
- **闭环**: 传简历+选轮次 → **岗位画像**（backend/web_research.py WebResearch：多搜索引擎抓取招聘要求+面经，AI 生成结构化画像 JSON，缓存 90 天，可指定公司并输出 hiring_status/salary/company_insights/sources）→ 简历匹配评分 → 拟真面试（WS 流式：question_token→音频→面试官切换→评估）→ 逐题评分 → 报告（雷达图、按面试官聚合均分、考察覆盖度）。
- **架构要点**: 9 阶段状态机（intro→resume→general_tech→deep_dive→project→pressure→hr→qna→end）；质量驱动阶段推进（均分≥75/回答≥150字/时间压力>70%/追问深度≥0.6 且分<70 时推迟推进）；面试官路由评分（阶段权重+追问加成+短答加成+压力+随机）；画像为公司定向搜索+如实降级；安全层 InputGuard/OutputGuard/StateVerifier/MemoryGuard 覆盖 8 种攻击（mock_interview/security.py）；API Key Fernet 加密只返掩码（settings_crypto.py）；训练数据采集+LoRA。
- **部署/成本**: `python run.py`（自动托管 frontend-vue/dist，端口 18633，自签名 HTTPS 供局域网麦克风）；env MIMO/DEEPSEEK/QWEN/ZHIPU_API_KEY、AI_PROVIDER、MySQL（否则 JSON 回退）、SECRET_KEY、SMTP。成本：国产模型为主，TTS/ASR 按会话计，画像缓存省成本。
- **亮点**: 四个中**最强的岗位人才画像落地**（运行时联网研究、公司定向、可复用画像对象）；9 阶段流程+动态推进+面试官路由；认真做 prompt 注入防御；BYOK 加密；语音优先实时。**不足**：仅个人练习（无企业/HR 端）、无视频、重度中文文档、MySQL 未配时降级 JSON。
- **可复用**: `backend/web_research.py`（**岗位画像生成器——差异化核心**）、`backend/mock_interview/mock_engine.py`+`mock_state.py`（9 阶段引擎+路由评分）、`backend/mock_interview/security.py`（5 层防护）、`backend/mock_interview/interviewer_config.py`（阶段提示词/主导角色）、`frontend-vue/src/services/asr.js`（FSM ASR）、`backend/cosyvoice_ws.py`（流式 TTS）、`backend/settings_crypto.py`（BYOK 加密）。

### Repo: interview-skills（jennifer88huang/interview-skills）
- **GitHub**: jennifer88huang/interview-skills。
- **形式**: text —— Claude/OpenClaw Agent Skill（纯提示词包）+ 浏览器 UI；无语音视频。
- **目标**: candidate practicing（大厂求职者；延伸=面试官/HR 校验简历）。
- **技术栈**: 无后端——SKILL.md+references/*.md 提示词资产；ui/index.html+app.js 直接调 OpenAI 兼容接口（deepseek/kimi/glm/minimax/xai/mistral/perplexity/openrouter），Key 仅存浏览器会话；pdf.js 解析简历；无 Key 时本地模拟。
- **闭环**: 输公司+岗位+JD+简历 → JD 解析（硬技能/软技能/隐藏考察点）+简历解析（亮点/缺口）+公司风格匹配（阿里味/字节范/Google…）→ 出 10 题（3-4 技术基础题取 JD 硬技能、3-4 项目深挖取简历+JD、1-2 行为面按公司文化、1 反问预测）+难度+参考答案提示+追问方向 + JD vs 简历匹配度分析 → 交互式追问演练（可多轮）。
- **架构要点**: 纯 prompt 工程+精选知识资产：references/company-profiles.md（各厂面试风格/筛人标准/流程，人工整理）、jd-parser.md（JD 措辞→考察点映射表）、resume-parser.md（数字挖掘/时间轴/技术栈差）、question-design.md、bei-framework.md（BEI/STAR）；SKILL.md 定义工作流+HR 面专项+谈薪话术+多轮连贯模拟；UI 状态 localStorage。
- **部署/成本**: 零部署（GitHub Pages 或 /skill install）；成本=用户自带 Key 的 token，本地模拟免费。
- **亮点**: 岗位画像思路完整（JD 解析+简历解析+公司画像+匹配度分析）；追问演练闭环；HR/谈薪专项；跨平台提示词资产可移植。**不足**: 无产品后端（无跨会话持久化除 localStorage）、无打分（定性）、无语音视频；质量依赖宿主 LLM。
- **可复用**: `SKILL.md`（工作流规范）、`references/jd-parser.md`、`references/resume-parser.md`、`references/company-profiles.md`（可直接作为岗位人才画像知识库）、`references/question-design.md`、`ui/app.js`（JD+简历表单+追问循环）。

## Group B — 面试视频/编码工具

### Repo: TalentIQ-Interview（Bhuvanesh3602/TalentIQ-Interview）
- **是什么**: 实时编码面试平台——"Google Meet + LeetCode + VS Code"：视频通话+协作 Monaco 编辑器+即时执行+聊天+会话管理+题库。
- **技术栈**: React18+Vite+Tailwind+DaisyUI+Monaco+TanStack Query；Express+MongoDB/Mongoose；Stream.io Video+Chat（托管实时）；Clerk 认证；Inngest 后台任务；Piston 执行（JS/Python/Java）；部署 Netlify/Render/Vercel 已配置。
- **闭环/架构**: host 建会话 → 后端建 Stream 视频 call+聊天 channel（callId）→ 分享链接加入（限 2 人、房间锁）→ Monaco 写码 → /api/code/execute 调 Piston 跑 → 聊天 → host 结束删除 Stream call+channel；Clerk user.created webhook→Inngest sync-user→Mongo+Stream 用户。
- **部署/成本**: backend npm run dev + Mongo，frontend 5173；env STREAM_API_KEY/SECRET、CLERK_PUBLISHABLE/SECRET、DB_URL、INNGEST_EVENT/SIGNING_KEY。成本=Stream 视频分钟、Clerk 席位、Piston 免费层、Mongo Atlas。
- **亮点/不足**: 托管实时（Stream）=零自研 WebRTC/信令；Clerk+Inngest 用户同步干净；可拖拽分栏；带 starter code 题库。**不足**: README 声称的录制在代码中**不存在**（全库 grep 无 record 实现）；无 AI 评分/报告层；Piston 外部依赖延迟；仅显式结束才清理会话；无记事本。
- **可复用**: `backend/src/controllers/sessionController.js`（会话↔Stream call 生命周期）、`backend/src/lib/piston.js`（执行封装）、`backend/src/lib/inngest.js`（Clerk webhook 用户同步模式）、`frontend/src/components/CodeEditorPanel.jsx`+`SessionPage.jsx`、`frontend/src/data/problems.js`（题库+starter code）、`netlify.toml/render.yaml/vercel.json`（部署配方）。

### Repo: CollabCode（humancto/CollabCode，OpenCollab）
- **是什么**: 技术面试/结对编程实时协作编码平台——ACE Editor+Firepad（Firebase RTDB 的 OT）协同编辑、Piston 浏览器内执行、管理员仪表盘、行为分析、结构化面试笔记/反馈、Slack 导出；无视频（roadmap）。
- **技术栈**: 原生 JS+Express；Firebase Realtime Database+Firepad OT+firebase-admin；JWT+bcrypt；ACE Editor；Piston；Vercel serverless functions；geoip-lite/request-ip/ua-parser 审计；PostHog；Slack webhook；helmet/rate-limit/dompurify。
- **闭环/架构**: 面试官 JWT 登录 → 创建会话（session code）→ 候选人零账号凭码加入 → ACE/Firepad 实时协同 → /api/code/execute→Piston 执行 → 行为追踪（tab 切换/粘贴/打字/失焦写入 RTDB，超阈值通知面试官）→ 结构化笔记（技能评分+录用建议，时间戳+代码引用）→ 结束 → 分析/导出（Slack/CSV）。
- **部署/成本**: Firebase 项目+Vercel 部署（env ADMIN_EMAIL/ADMIN_PASSWORD_HASH/JWT_SECRET/FIREBASE_*）；本地 node serve.js。成本=Firebase RTDB 读写（便宜）+Piston 免费。
- **亮点/不足**: 候选人零门槛（无账号）；serverless-first（无常驻服务器、无自研信令）；真反作弊分析（tab/粘贴监控带严重级别）；结构化反馈+录用建议；笔记带时间戳与代码引用；安全配置认真。**不足**: 无音视频/聊天（README comig soon）；ACE 非 Monaco；无 AI 评估；README 的 10000+ 场访谈徽章与"成功案例"明显注水；单一 admin 模型。
- **可复用**: `scripts/firepad.js`（Firebase+Firepad 协同初始化）、`scripts/behavior-tracking.js`+`activity-monitor.js`（反作弊分析）、`scripts/interview-notes.js`（带评分的结构化反馈）、`api/code/execute.js`（Piston 代理）、`api/sessions/create.js`、`database.rules.secure.json`（RTDB 安全规则）、`vercel.json`（安全头配置）。

## 横向观察：岗位人才画像实现度排名（对我们的差异化最相关）

1. **MockMate 最佳**——`backend/web_research.py` 是**运行时数据管线**：联网抓取目标岗位 JD+面经（可指定公司），AI 生成结构化画像 JSON（技能/考察点/招聘状态/薪资/公司洞察/来源），缓存 90 天；画像随后用于简历匹配评分并注入每道题 prompt。**这是真正的、可复用的、数据驱动的岗位画像对象。**
2. **AI-Interview 次之**——从 JD+简历一次性生成 job details/panelist 人设/编码任务/候选画像，但是每配置一次性的静态产物，无持续联网研究；onboarding_data 含真实公司案例。
3. **interview-skills 第三**——有最完整的**画像提示词设计**（JD 解析维度+人工整理的 company-profiles 公司画像+简历解析+匹配度分析），但属静态 markdown+prompt，非运行管线；作为知识层可直接复用。
4. **NextStep.AI 最后**——简历+JD 用于生成 prep report 与岗位题库，无独立可复用画像对象。

**两个视频工具相对前一批的增量**：
- 前一批（Interview4Me/PeerJS+Socket.IO、interview_platform1/WebRTC+Yjs、live-code-interviewer/SuperViz+AI 转写报告、livecoding/纯 CRDT）均为 DIY 实时与协作。
- **TalentIQ** 新增：托管实时方案（Stream 视频+聊天 SDK、Clerk 认证、Inngest webhook 用户同步）——免自研信令；完整部署配方；带 starter code 题库与运行闭环。注意其"录制"是 README 注水。
- **CollabCode** 新增：serverless-first 架构（Firebase RTDB+Firepad OT+Vercel 函数，无常驻服务）；前一批普遍缺失的**评估层**——行为/反作弊分析（tab 切换、粘贴、打字）、结构化面试笔记+技能评分+录用建议、Slack/CSV 导出、候选人零账号加入。
