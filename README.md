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
| **登录 + 平台闭环** | 本地账号 + 密码；数据全存独立盘 `/data/probedesk`（SQLite），不占系统盘。管理简历（**支持上传 PDF/Word/Markdown/TXT/Excel，后端自动解码**；多份/默认/技能画像）、预约、面试列表、报告、学习曲线 |
| **预约 → 面试** | 填简历 + 公司/岗位/JD + 时间 + 是否含手撕 + 场景(含保研) + **面试官人格** + **面试方案(真实对话/按住说话/文字对话)** → 生成一场**真实、有状态机**的面试 |
| **明确的状态机面试流程（核心）** | AI 面试官按**明确状态机**推进，而非"后台搜题一个个抛给候选人"：**自我介绍 → 介绍项目 → 提问项目 → 提问其他能力/知识 → 提问对岗位的看法 → 手撕代码 → 收尾**。每个环节由**确定性回合数**推进（测试可快速走到每个状态）；**每一轮都在后端重建一个 agent**，其 prompt 含：面试官身份(人格) + **你的简历** + **本场特殊要求(岗位/JD/场景/补充)** + **你和它全部的历史对话** + 当前环节指引。**优先用纯文字流**验证每个状态 agent 的输入输出；另外两种流只是在这个 agent 核心上接 STT/TTS |
| **三种面试方案（可预约时选）** | ①**真实对话(全双工)** 麦克风常开、边说边答，AI 实时语音（像打电话，可打断）；②**按住说话(PTT)** 按住说话、松开识别，更稳定不误触发；③**文字对话** 打字一问一答，最稳最快。三者都走**同一个后端 agent**（面试流程与追问一致），只是输入/输出通道不同 |
| **真实语音面试** | 全双工：流式 STT(Volcengine) + 流式 TTS(MiniMax)，单 WS 持续收发，**可打断**；按住说话：WebAudio 采集 → Volcengine STT → DeepSeek 大脑 → MiniMax 回放 |
| **视频面试间（LiveKit · 以 livekit-meet 组件为基地）** | 用 livekit-meet 同款组件库 `@livekit/components-react`（`VideoConference`）在 ProbeDesk 内重排成**面试态房间**：候选人**摄像头/麦克风/共享全屏**（meet 同款网格与控制条，本地预览正常）+ AI 面试官头像；真实音视频走自托管 LiveKit（`wss://voice.windgraham.art`） |
| **手撕代码** | 到 coding 环节出现**按岗位自动匹配的题库题**（本地 150 题）与代码编辑器；**AI 面试官实时读取并评判候选人的代码**（静态分析 + 提示阶梯） |
| **AI 看屏幕** | 候选人可"让面试官看我的屏幕" → Gemini 视觉理解和描述共享画面（AI 读视频流能力） |
| **信息充分** | Researcher 层在预约时检索（搜索引擎 + 牛客面经 + Tavily + **小红书/知乎[真实浏览器登录态]**）→ 结构化成**岗位画像**（技能/考察点/公司流程/高频题），注入出题，问得比通用 AI 更准 |
| **可执行反馈** | `interviewer_os`：事后给出 **missing_slots → what_i_want_to_hear → 一句话改进建议**（带候选人原话证据），只在报告呈现，面试中不实时展示 |
| **三大"比 ChatGPT 更好"差异化** | ①**人格分层**（同级/资深同级/主管决定面试官语气与出题风格）；②**跨场记忆/学习曲线**（每场结果落库，下一场注入你上次的薄弱项，报告页有多场趋势+薄弱项+重练入口）；③**按岗位自动配题**（岗位技术栈关键词→算法 tag→题库选题） |
| **转写 + 分享 + 录制** | 全程问答转写可下载；**公开只读分享页** `/share/{id}` 转发给他人评价；**语音回顾**合成报告音频 |

---

## 技术栈
- **底层**：Next.js 16（App Router）+ livekit-client / livekit-server-sdk + Tailwind 4（前端）；FastAPI + Pydantic + httpx（agent）
- **LLM**：DeepSeek（OpenAI 兼容，大脑/出题/评分/判码）；Gemini 视觉（aixhan 中转，AI 看屏幕）
- **语音**：Volcengine（STT）+ MiniMax（TTS）
- **信息搜索**：多引擎聚合 + 牛客匿名面经 + Tavily（可选）+ 小红书/知乎（feature flag）
- **题库**：离线 LeetCode-CN 150 题（本地 `data/problems.json`，不做运行时抓取）
- **过程**：借鉴 DeepInterview 的 prep→live→post。**live 阶段由"每轮重建的 agent"(liveflow) 主持**——真正有时间概念、逐层追问，而非走死板游标；**prep 的计划 + post 的记分卡**仍用于**报告评分**（每轮动态题会被记录进计划供 `/report` 打分），因此**无硬状态机**、可优雅降级。反馈内核参考学长 ProjectProbe 的 `interviewer_os`（仅报告可见）

---

## 仓库结构
```
apps/
  agent/     Python FastAPI + LiveKit Agents 思路（AI 面试官大脑 + 语音 + 信息搜索 + 判码 + 报告）
            ├── src/agent/{prep,pipeline,coding,researcher,harness,stt,tts,llm,contracts,config,main}.py
            └── scripts/、tests/、data/problems.json
  web/       Next.js 16 平台前端（首页/预约/房间/报告/分享）
packages/
  shared/    类型契约（zod ↔ Pydantic）
docs/        文档（开发流程 / API密钥清单 / 产品方案 / 文档导航）
research/    调研资料库（外部开源项目代码级分析，不入产品构建）
```

---

## 快速开始

```bash
# 1) 配置 .env（见 docs/API与密钥清单.md，复制 .env.example）
cd apps/agent && cp .env.example .env   # 填入 DEEPSEEK / GEMINI / VOLCENGINE / MINIMAX 等 key

# 2) 启动 agent API（:8000）
cd apps/agent && python -m venv .venv && .venv/bin/pip install -e .
PYTHONPATH=src .venv/bin/python -m uvicorn agent.main:app --port 8000

# 3) 启动前端（:3101）
cd apps/web && pnpm install && pnpm dev
# 打开 http://127.0.0.1:3101 → 预约 → 面试房间 → 报告
```

> 无任何 key 也能构建/渲染（mock-first）；语音/看屏/判码需对应 key。

---

## 关键 API
- `POST /api/interviews/prepare`（简历/JD/公司/岗位 → 生成面试计划）
- `GET /api/interviews/{id}/next` · `POST /api/interviews/{id}/answer`（文字轮次）
- `POST /api/voice/answer`（STT → 大脑 → TTS 语音轮）
- `GET /api/interviews/{id}/problem` · `POST /api/coding/judge`（手撕代码判分）
- `POST /api/vision/analyze`（Gemini 看屏幕/图像）
- `GET /api/interviews/{id}/report`（报告 + interviewer_os）
- `GET /api/interviews/{id}/transcript` · `GET /api/interviews/{id}/recap`（转写/语音回顾）

---

## 开发流程（如何迭代而来）
见 `docs/开发流程-迭代起点.md`。按 **Phase 0→6** 推进，每阶段**真实 API 测试 + 对抗性审查 + 独立 commit**（共 13+ 次干净提交）。核心先做**大脑纯文本闭环 + 双 agent 互聊测试 + 离线题库**（零第三方 key 验证差异化），再盖语音（Phase 3）、手撕代码+看屏（Phase 4）、转写分享录制（Phase 5）。

## 文档
- `docs/开发流程-迭代起点.md` —— 统一架构 + 迭代阶段 + 借码清单
- `docs/API与密钥清单.md` —— 所需全部 API/凭据
- `docs/产品方案-设计分析.md` —— 产品/模块/评审对照
- `docs/README.md` —— 文档导航
