# AIIC · ProbeDesk — AI 面试官平台 (Live)

> **Demo 公开访问：<https://mock.windgraham.art>**（已部署，HTTPS 证书 2026-11-28 到期、自动续期；Nginx 反代到 :3101，agent API 在 :8000）
>
> 一个 **LiveKit 风格的 AI 模拟面试官平台**（面向计算机算法 / 研发岗），提交 2026-08-30「AI 模拟面试官」项目挑战。
>
> **不是"AI 问答"，而是"AI 面试官"平台**：学员在这里预约一次针对某公司/某岗位的面试 → 进入真实面试间（语音对话 / 手撕代码 / 共享屏幕）→ AI 面试官实时提问、追问、打分 → 面试后给一份**可执行的评价报告**（缺了哪些点、面试官想听到什么、下一步怎么练），且**全程转写与录制可转发分享**。

---

## 核心能力（全部为真实 API 驱动，非 mock）

| 能力 | 说明 |
|---|---|
| **登录 + 平台闭环** | 本地账号 + 密码；数据全存独立盘 `/data/probedesk`（SQLite），不占系统盘。管理**简历**（支持上传 PDF/Word/Markdown/TXT/Excel，后端自动解码；多份/默认/技能画像）与**公司/岗位 JD**（可提前设置多份、设默认，预约时一键带入）；预约、面试列表、报告、学习曲线 |
| **后台准备(预约即开始)** | 预约**一提交即后台并行准备**（Researcher 岗位信息搜索 + 出题 + 简历/JD 解析），到点/尽快开始即可直接用；面试列表实时显示**后台准备状态**（🟡 准备中 / 🟢 已准备完毕 / 🔴 失败） |
| **预约 → 面试** | 填简历 + 公司/岗位/JD + 时间 + 是否含手撕 + 场景(含保研) + **面试官人格** + **严格程度(宽松/标准/严格)** + **面试方案(真实对话/按住说话/文字对话)** + **尽快开始/预约制(至少30分钟后)** |
| **明确的状态机面试流程（核心）** | AI 面试官按**明确状态机**推进，而非"后台搜题一个个抛给候选人"：**自我介绍 → 介绍项目 → 提问项目 → 提问其他能力/知识 → 提问对岗位的看法 → 手撕代码 → 收尾**。每个环节由**确定性回合数**推进（测试可快速走到每个状态）；**每一轮都在后端重建一个 agent**，其 prompt 含：面试官身份(人格) + **你的简历** + **本场特殊要求(岗位/JD/场景/补充)** + **你和它全部的历史对话** + 当前环节指引 + **严格程度** + **看屏幕旁注** |
| **三种面试方案（可预约时选）** | ①**真实对话(全双工)** 麦克风常开、边说边答，AI 实时语音（像打电话，可打断，**每次回复文字+语音一并自动播放**）；②**按住说话(PTT)** 点击录音/再点停止发送，更稳定；③**文字对话** 打字一问一答，最稳最快。三者都走**同一个后端 agent**，只是输入/输出通道不同 |
| **真实语音面试** | 流式 STT(Volcengine) + TTS(MiniMax，**先生成完整语音再随文字一起下发并自动播放**)；全双工单 WS 持续收发、可打断 |
| **视频面试间（LiveKit · 以 livekit-meet 组件为基地）** | `@livekit/components-react`（`VideoConference`）在 ProbeDesk 内重排成**面试态房间**：候选人**摄像头/麦克风/共享全屏**（meet 同款网格与控制条）+ AI 面试官头像；右侧竖列设备控制（📷/🖥️/🎙️/💬）+ 小缩略图，左屏对话；真实音视频走自托管 LiveKit（`wss://voice.windgraham.art`） |
| **功能测试(`/self-test`)** | 与真实面试完全相同但无 AI 进入，自测：A 语音↔文字(STT)↔TTS 语音；B 开摄像头/共享→**实时流读屏**滚动列表；C **搜索能力**；D **LLM 接口** |
| **手撕代码** | 到 coding 环节出现**按岗位自动匹配的题库题**（本地 150 题）与 **CodeMirror 6 编辑器**（Python/C++/JS 语法高亮 + 自动缩进）；**AI 实时读码判分**（静态分析 + 提示阶梯）。面试中可点「⚡手撕代码」一键跳到该环节 |
| **AI 看屏幕（实时视频流）** | 候选人开摄像头/共享即**实时抽帧→Kimi K2.7 读屏→旁注喂给 agent**（关掉即停止），agent 能看到每帧画面内容并在对话中自然提及 |
| **信息充分** | Researcher 层在预约时并发检索（搜索引擎 + 牛客面经 + Tavily + **小红书/知乎真实浏览器登录态**，上限 100 条）→ 结构化**岗位画像**注入出题，问得比通用 AI 更准 |
| **可执行反馈** | `interviewer_os`：事后给出 **missing_slots → what_i_want_to_hear → 一句话改进建议**（带候选人原话证据），只在报告呈现，面试中不实时展示 |
| **面试总结文档** | 面试完成后一键生成**完整 Markdown 总结**（逐环节问答、分项评分、缺失项、改进建议），可查看/下载 |
| **三大"比 ChatGPT 更好"差异化** | ①**人格分层 + 严格程度**（同级/资深同级/主管 × 宽松/标准/严格，决定语气、追问深度与评分口径）；②**跨场记忆/学习曲线**（每场结果落库，下一场注入上次薄弱项）；③**按岗位自动配题**（岗位技术栈关键词→算法 tag→题库选题） |
| **转写 + 分享 + 录制** | 全程问答转写可下载；**公开只读分享页** `/share/{id}` 转发评价；**语音回顾**；**浏览器录制（麦克风+屏幕）上传落盘** + 会话数据(交谈+转写)全部持久化 |

---

## 技术栈
- **底层**：Next.js 16（App Router）+ livekit-client / livekit-server-sdk + Tailwind 4（前端）；FastAPI + Pydantic + httpx（agent）
- **LLM**：DeepSeek（OpenAI 兼容，大脑/出题/评分/判码）；**Kimi Code K2.7**（视觉读屏）
- **语音**：Volcengine（STT）+ MiniMax（TTS）
- **信息搜索**：多引擎聚合 + 牛客 + Tavily（可选）+ 小红书/知乎（真实浏览器登录态，上限 100）
- **代码编辑器**：CodeMirror 6（Python/C++/JS 高亮 + 自动缩进）
- **题库**：离线 LeetCode-CN 150 题（本地 `data/problems.json`，不做运行时抓取）
- **过程**：借鉴 DeepInterview 的 prep→live→post。**live 阶段由"每轮重建的 agent"(liveflow) 按明确状态机**主持（自我介绍→项目→提问项目→其他能力→岗位看法→手撕→收尾，每环节确定性回合数 + 时间兜底）；**prep 的计划 + post 的记分卡**用于**报告评分**。反馈内核参考学长 ProjectProbe 的 `interviewer_os`（仅报告可见）

## 安全（凭据不入库）
- **所有 API key 都在** `apps/agent/.env`、`apps/web/.env`（**已 gitignore**，数据库/仓库不含任何真实 key）。
- 提交到仓库的只有 **`.env.example`（占位符）**，不含任何真实密钥。
- 服务器部署的真实 `.env` 在 `/data/probedesk` 下运行平台的 systemd 服务里，不在仓库内。
- 请勿把真实 `.env` / 私钥 / cookie 提交到 git；本地开发时复制 `.env.example` 为 `.env` 再填入。

## 仓库结构
```
apps/
  agent/     Python FastAPI + LiveKit 思路（AI 面试官大脑 + 语音 + 信息搜索 + 判码 + 报告）
            ├── src/agent/{liveflow,prep,pipeline,coding,researcher,stt,tts,llm,resume_parse,livekit_bridge,contracts,config,main}.py
            └── scripts/、tests/、data/problems.json
  web/       Next.js 16 平台前端（首页/预约/房间/报告/分享/功能测试）
packages/
  shared/    类型契约（zod ↔ Pydantic）
docs/        文档（开发流程 / API密钥清单 / 产品方案 / 文档导航 / 提交包）
research/    调研资料库（外部开源项目代码级分析，不入产品构建）
```

---

## 快速开始

```bash
# 1) 配置 .env（见 docs/API与密钥清单.md，复制 .env.example，勿提交真实 key）
cd apps/agent && cp .env.example .env   # 填入 DEEPSEEK / KIMI / VOLCENGINE / MINIMAX / LIVEKIT 等 key

# 2) 启动 agent API（:8000）
cd apps/agent && python -m venv .venv && .venv/bin/pip install -e .
PYTHONPATH=src .venv/bin/python -m uvicorn agent.main:app --port 8000

# 3) 启动前端（:3101）
cd apps/web && pnpm install && pnpm build && pnpm start   # 或 pnpm dev
# 打开 http://127.0.0.1:3101 → 登录/注册 → 预约 → 面试房间 → 报告 → 总结文档
```

> 无任何 key 也能构建/渲染（mock-first）；语音/看屏/判码/搜索需对应 key（已配置于部署机 `.env`）。

---

## 关键 API
- `POST /api/auth/register|login`（账号）· `GET/POST /api/resumes`、`/api/jds`（简历 / 岗位位 JD 管理）
- `POST /api/interviews/book`（预约，含 jd_id/asap/strictness）· `GET /api/interviews`（列表，含 prep 状态）
- `POST /api/interviews/{booking}/start` · `GET /api/interviews/{id}/next`（准备状态/开场）
- `POST /api/interviews/{id}/answer`（文字轮）· `GET /api/interviews/{id}/code`（跳到手撕环节）
- `POST /api/voice/answer` · `POST /api/voice/stt` · `POST /api/voice/tts`（语音）
- `POST /api/vision/analyze` · `/api/vision/analyze-batch`（Kimi 读屏/看屏）
- `POST /api/search`（信息检索，上限 100）· `POST /api/llm/ping`（LLM 连通性测试）
- `GET /api/interviews/{id}/problem` · `POST /api/coding/judge`（手撕判分）
- `GET /api/interviews/{id}/report`（报告 + interviewer_os）
- `GET /api/interviews/{id}/summary`（完整 Markdown 总结文档）
- `POST /api/interviews/{id}/screen-note` · `/save-transcript` · `/recording`（读屏旁注 / 转写 / 录制持久化）

---

## 开发流程（如何迭代而来）
见 `docs/开发流程-迭代起点.md`。按 **Phase 0→6** 推进，每阶段**真实 API 测试 + 对抗性审查 + 独立 commit**（共 13+ 次干净提交）。核心先做**大脑纯文本闭环 + 双 agent 互聊测试 + 离线题库**（零第三方 key 验证差异化），再盖语音（Phase 3）、手撕代码+看屏（Phase 4）、转写分享录制（Phase 5）。

## 文档
- `docs/开发流程-迭代起点.md` —— 统一架构 + 迭代阶段 + 借码清单
- `docs/API与密钥清单.md` —— 所需全部 API/凭据
- `docs/产品方案-设计分析.md` —— 产品/模块/评审对照
- `docs/README.md` —— 文档导航
