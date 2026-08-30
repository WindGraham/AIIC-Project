# AI 模拟面试方案 · 开源项目深入分析

> 只读本地仓库实际代码（非 README 宣传），每个仓库给出：形式、目标、技术栈、闭环、架构要点、部署/成本、亮点、不足/差异化机会、可复用模块。
> 已克隆 16 个（另有 6 个因网络未能克隆，见 `未克隆仓库参考.md`，此处以 web README 摘要为准）。

## 目录（已分析）
- [汉语族：简历+JD 定制 + 追问 + 评分 + 报告](#汉语族)
- [WebRTC/视频/数字人 组](#webrtc视频数字人-组)
- [DeepInterview（深度）](#deepinterview深度)
- [语音/LiveKit/本地 LLM 组](#语音livekit本地-llm-组)

> WebRTC/数字人 六仓库完整逐仓库分析另见 `ai-mock-interview-analysis.md`；语音/LiveKit/本地 LLM 六仓库完整分析另见 `分析-AI模拟面试方案-voice组.md`（均为子代理实读代码产出）。

---

## 汉语族：简历+JD 定制 + 追问 + 评分 + 报告

### Repo: offerMaster（heatnan/offerMaster）
- **形式**：**voice** —— push-to-talk 录音 → Whisper 转写 → AI 语音回应（edge-tts）；文字输入仅作转写纠错兜底。
- **目标**：候选人陪练（README 虽提 HR/培训机构，但闭环是候选人）。
- **技术栈**：Next.js14+TS+Tailwind（前端）；FastAPI+SQLAlchemy+MySQL8（后端）；LLM=OpenAI 兼容协议默认 **DeepSeek**；STT=faster-whisper 本地（默认）/火山豆包流式 ASR；TTS=edge-tts（默认免费）/豆包 Seed TTS；realtime=仅火山 ASR 走 WebSocket 流式。
  - ⚠️ **LangGraph 名义存在但未真正使用**（依赖在 requirements.txt，代码零导入；`nodes.py` 注释自述"functional nodes rather than a fully autonomous graph"，实际由 FastAPI 轮询状态机驱动）。
- **闭环**：上传简历(PDF/DOCX)+JD → 选 1~3 轮(peer/high_peer/manager 人格) → LLM 结合简历+JD 现场出 5~8 题(第1轮固定自我介绍) → push-to-talk 作答 → 转写 → 智能追问/推进+口头衔接语 → 每题异步评分 → 均分≥70 晋级 → 结束自动生成 Markdown+PDF 面评。
- **架构要点**：
  - 简历+JD 定制：`plan_questions` 注入 resume[:6000]+jd[:3000]，按轮次注入不同出题风格（一轮实操、二轮系统设计、三轮开放认知）。
  - 去重：LLM 出题后做"同题文本+同topic"双重去重，落库再 DB 侧去重防并发。
  - 追问：MAX_FOLLOWUPS=2、激进度配置(aggressive/balanced/lenient)、跨题历史记忆(可抓前后矛盾)、**追问必须引用候选人原话**；插追问删队尾未答主问题控制时长。
  - 评分：按角色换维度(tech/expression/depth vs manager 的 insight/communication/seniority)；prompt 写"语音转写宽容条款"(不因 ASR 错词/口头禅/未口述代码扣分)。
  - 报告：LLM 单次生成 Markdown → weasyprint 转 PDF。
  - 健壮性：评分后台线程(A+B 延迟优化)、TTS 预生成+轮询就绪、ack 音频即时播放、TTS 失败降级纯文本、重复提交幂等(UPSERT)。
- **部署/成本**：docker compose(mysql+backend+frontend)，首次下载 Whisper ~1.5GB；DeepSeek ≈¥0.3/场、edge-tts 免费、豆包 TTS ≈¥0.05/场、火山 ASR 试用20h/资源包 ¥900 起。
- **亮点**：追问引原话+ack 衔接语(最强的真人感)；三档人格拉开且评分维度分层；语音评分对 ASR 噪声的宽容条款同类少见；容错细节非常工程化。
- **不足/差异化机会**：无用户/历史管理；每轮题目全由 LLM 现场生成无题库→成本与方差高；无实时全双工语音；无 Avatar；MySQL+WeasyPrint 偏重；langgraph 是摆设。
- **可复用**：`agent/prompts.py`(人格/追问/语音宽容评分)、`agent/nodes.py`(出题/追问/评分+去重+兜底)、`api/interviews.py`(轮询状态机+异步评分+TTS 预生成)、`services/voice.py`(STT/TTS 抽象+火山二进制 WS 协议)、`services/report_pdf.py`、`frontend/app/interview/[id]/page.tsx`(push-to-talk+轮询 TTS)。

### Repo: ai-mock-interview（lhw12138）
- **形式**：**text + voice** —— 语音答题(讯飞流式听写,浏览器直连 WS,服务端只发签名 URL)、文字答题、浏览器 speechSynthesis 念题；无摄像头/Avatar，是双通道文本型问答。
- **目标**：候选人（"面向求职者"）。
- **技术栈**：Next.js16 App Router + React18 + TS + Tailwind + shadcn 风格；纯 Next.js API Routes（Node runtime）+ Vercel AI SDK(streamObject/generateObject)；LLM=DeepSeek 默认(内置智谱 GLM-4.5-Flash 免费预设,支持用户 BYO 任意 OpenAI 兼容模型)；STT=讯飞语音听写流式(60s 自动续接)+Web Speech API 兜底；TTS=仅浏览器 speechSynthesis；无 agent 框架(每轮 streamObject+zod schema 出结构化 JSON,客户端确定性状态机)。
- **闭环**：免注册选岗位(8角色) → 练习/模拟模式+职级+轮次+题量(可粘简历/JD) → 题库取题(100题/角色带参考答案) → 逐题语音/文字作答、最多2轮追问 → 生成五维证据化评分报告(区间/量表/原话证据/改写示例) → 最弱维度5题专项训练+逐题重答 → 历史20场趋势(localStorage)。
- **架构要点**：
  - 简历+JD：`api/resume/route.ts` 用 LLM 生成3道定制题,与题库混排(题库补足剩余)。
  - 去重：题目ID强校验 + `avoidRecent` 排除近3场已出题。
  - 追问：≤2轮,系统提示强制"进下一题时逐字念下一题原文"防 LLM 篡改题面。
  - 评分：按岗位5维加权(产品 logic/productSense/…,技术 techDepth/systemDesign/…)；报告 prompt 强制 rubric-v2 分数带、原话证据、confidence、不虚构的 improvedAnswer；总分服务端按权重重算。
  - 报告闭环：PDF(打印)、二维码分享海报、最弱维度专项训练、逐题重答。
  - 存储：全 localStorage/sessionStorage(游客免注册),结构化校验读写,支持导入/导出/清空。
  - 安全：同源校验、限流、自定义 baseUrl 阻断本机/私网/云元数据(SSRF 防护)、密钥仅存 sessionStorage(带单测)。
  - 部署：Vercel 或 Docker+Caddy 或阿里云 FC 按量。
- **部署/成本**：仅需 DeepSeek+讯飞两组密钥,无数据库；成本=DeepSeek token(可切 GLM-4.5-Flash 免费)+讯飞按量；serverless 友好。
- **亮点**：题库体量大且质量高(约630+题,每题带参考要点)；"诊断→训练→重考→看进步"闭环完整;**最弱维度专项训练是最独特设计**；证据+置信度+改写示例让 AI 评分可审计；安全与输入校验远超同类；有 vitest 单测。
- **不足/差异化机会**：纯本地存储→换设备丢数据,无法做跨场次成长曲线和分享给导师/HR；TTS 仅浏览器合成无音色/情感；追问浅(2轮封顶、无跨题矛盾检测,对比 offerMaster 引用式追问)；题库固定→未传简历时体验完全静态；无多人格/多轮差异化；无语音评测(不测发音/流利度)。
- **可复用**：`lib/prompts.ts`(报告 prompt,rubric-v2/证据/improvedAnswer)、`lib/score.ts`(岗位加权维度表)、`lib/asr/iat-asr.ts`+`api/asr/auth/route.ts`(服务端签URL、浏览器直连讯飞 WS 的免代理 ASR)、`lib/api-security.ts`(BYO-Key 的 SSRF/限流)、`lib/storage.ts`(游客持久化)、`lib/question-banks/*.json`(100题/岗位带参考答案,可直接借题)。

### Repo: interview-copilot（20529shanghai）
- **形式**：**text** —— 它**不是**模拟面试,而是面试官的实时"副驾"：捕获会议系统音频或手动录入 → 转写 → LLM 生成面试官下一句可直接说出口的话+证据+风险+评分。核心输出是文本建议,无语音合成。
- **目标**：recruiter screening(面试官侧实时辅助)。
- **技术栈**：Electron43+原生JS渲染层+preload IPC；无独立后端(全在 Electron main 进程+直连 DeepSeek fetch)；LLM=DeepSeek/OpenAI兼容(默认 deepseek-v4-flash,json_object+thinking:disabled)；STT=腾讯云ASR(SentenceRecognition 单句识别+TC3-HMAC 手写签名)；TTS 无；无 agent 框架(单次 JSON 分析)；realtime=半实时(getDisplayMedia 抓系统音频 loopback + 转写追加,AbortController 可取消)。
- **闭环**：开会/面试中抓系统音频或手动补录 → 转写去重/归一化 → 本地知识库(md/txt/html/docx/pdf 分块检索)或 iMA 远程库 → 发送最近14条对话+候选人描述 → DeepSeek 返回 nextQuestion/评分/分层/风险 → 展示"下一句" → 会话结束归档为 交流记录.json + 分析报告.md。
- **架构要点**：转写去重(bigram≥0.92 判重复,跨说话人≥0.82 标"疑似复述,分析降权")；本地 RAG(自研900字chunk+120 overlap,CJK 单字/双字 tokenize,权重检索,评分标准类目×1.12 加权)——无向量库的轻量方案；评分5维(technical/communication/credibility/resourceFit/roleFit)+candidateTier 四档+risk,硬性规定"若候选人刚提问,nextQuestion 必须作答而非追问"；API Key 用 Electron safeStorage 加密；输出做敏感信息清洗。
- **部署/成本**：`npm install && npm start`,`npm run dist` 打包 win32；成本=DeepSeek+腾讯 ASR 按量。
- **亮点**：切中真实缺口——面试官侧实时辅助(同类多为候选人陪练)；本地知识库让学校/公司标准可注入；安全设计；带 JD/评分标准模板。
- **不足/差异化机会**：硬编码输出路径 `F:\2026\新生信息文件夹`(个人配置残留,换机器即坏)；Windows-only、单句 ASR 非流式；无 LLM 流式；分析只看最近14条,长面试早期信息丢失；无候选人跨场档案；无"建议是否被采纳"的闭环评估。新产品机会：流式全双工 ASR、按面试阶段自动触发分析、候选人跨场画像、面试官与候选人双视角。
- **可复用**：`lib/knowledge.js`(无依赖分块/分词/检索 RAG,extractText 覆盖6种格式)、`lib/deepseek.js`(JSON 模式分析 prompt+校验)、`lib/tencent-asr.js`(手写 TC3-HMAC 签名)、`templates/评分标准模板.md`+`岗位JD模板.md`(可复用面试标准模板)、`textSimilarity`/`findDuplicateTranscript`(转写去重)。

---

## DeepInterview（深度）

> 全仓库架构最完整、工程化最高的参考（pnpm+turborepo monorepo：apps/agent、apps/web、cli、packages/shared、services/lightrag、supabase、skills 题库包）。

- **定位**：candidate-practice 型、voice-first、多语言 AI mock interview；open-core——OSS 自托管匿名可用，Supabase auth/计费只在 hosted 版（`0006_drop_billing.sql` 已删计费）。
- **语音**：LiveKit **全双工**房间 + cascaded STT→LLM→TTS（livekit-agents 1.6 AgentSession, `worker.py`）。ASR: Deepgram nova-3/nova-2、Soniox、本地 Whisper（StreamAdapter 无 interim）；TTS: Cartesia/ElevenLabs/Gemini、本地 Kokoro；live LLM: Gemini 3.5 Flash Lite，prep/scoring: Gemini 3.6 Flash。**prep/post 全程有 mock 适配器离线跑通，但 live worker 无 mock 语音、缺 key 直接拒启**。
- **三段式管线**：
  - prep = LangGraph fan-out：`cv_analysis/jd_analysis/company_research → gap_matching → question_planner`（`prep/graph.py`+`prep/nodes.py`）；markitdown 解析简历（Gemini 兜底，`prep/cv_extract.py`）；题库包注入（`_skill_library_hint`）。
  - live = lean 单模型 + 7 个 function tools（含 handoff 到 coding/behavioral 人格）、TranscriptFlusher checkpoint、SessionGuard 20 分钟/80 turn 上限、`reconstruct_answers`（`live/state.py`、`worker.py`）。
  - post = `run_score`: evaluate → language_coach → report（逐阶段超时+降级，`post/evaluator.py`）；再进入 Study Coach（仅当设置 LIGHTRAG_URL 才接地）。
- **最可复用资产**：`InterviewContext` 黑板书契约（TS↔Pydantic parity）、mock-first 适配层（`core/adapters/*`+`build_mock`）、`skills/` 题库包格式 + `SCHEMA.md` 检索、persona/语言包扩展点（`personas.ts`、`worker.py` language maps）。
- **最大的坑/过度设计**："LightRAG" 侧车实为**内存 NaiveRAG**（真 LightRAG 后端是 `NotImplementedError` 骨架）；avatar 全是 404 占位符（渲染成渐变舞台）；OSS 里 billing+auth 是死重；本地 whisper 是批量（无逐词字幕）、Kokoro 无 vi、nova-3+vi 有 bug、OpenAI 模型未验证。
- **对 16h MVP 的启示**：抄袭它的「prep(重预算)→live(轻)→post(分阶段评分+降级)」三层契约 + mock-first（离线也能开发/演示），但**放弃** livekit 全双工+云 key 的重投入，改成「push-to-talk 本地 Whisper + 免费 TTS」即可在 10h 内跑通。

---

## 汉语族跨项目观察
- **产品闭环抄 lhw12138/ai-mock-interview**：8 个校招友好岗位×100题带参考答案(本科生需要"学内容")、免注册即用、最弱维度专项训练+逐题重答+历史趋势——唯一把"练习→诊断→再练→看见进步"做成完整循环的。
- **对话智能抄 offerMaster**：简历+JD 动态出题、引用原话的追问、三档人格、语音宽容评分——lhw 追问太浅,offerMaster 的 prompt 设计可移植。
- **成本模型抄 offerMaster**：DeepSeek 主模型+免费/低价 TTS(edge-tts/浏览器 speechSynthesis),一场≈¥0.3 才支撑免费体验。
- **三者共同忽视**：无间隔重复/定时训练；无跨场次技能状态追踪(每维度进步曲线)；无校招特有场景(自我介绍、STAR 行为题教练、群面/笔试)；无实时全双工语音；无评估校准(verbosity bias/前后一致性)；无商业化/协作(全 BYO-Key/纯本地,无账号体系)。
