# AIIC · ProbeDesk — AI 面试官平台

> LiveKit 驱动的 **AI 模拟面试官平台**（面向计算机算法 / 研发岗）。提交 2026-08-30「AI 模拟面试官」项目挑战。
>
> 一句话：**不是一个"AI 问答"，而是一个"AI 面试官"平台**——学员在这个平台上预约一次针对某公司/某岗位的面试，进一个真实的面试房间（语音/视频/共享屏幕/手撕代码），AI 面试官实时提问、追问、打分，面试后给一份**可执行的评价报告**（缺了哪些点、我想听到什么、下一步怎么练），且**全程转写与录制可转发分享**。

## 文档
- **[开发流程-迭代起点](./docs/开发流程-迭代起点.md)** —— 统一架构 + 开发流程 + 迭代起点（主文档）
- **[API 与密钥清单](./docs/API与密钥清单.md)** —— 需要的全部 API/凭据
- **[产品方案-设计分析](./docs/产品方案-设计分析.md)** —— 产品/模块/评审对照
- **[文档导航](./docs/README.md)**

## 仓库结构
```
apps/
  agent/      Python FastAPI + LiveKit Agents（AI 面试官大脑 + 语音壳 + 信息搜索 Researcher）
  web/        Next.js 16 平台前端（预约/简历/列表/房间/报告/分享）
packages/
  shared/     类型契约（zod ↔ Pydantic）
docs/         文档
research/     调研资料库（20 个 AI 模拟面试 + 6 个视频面试工具 + DeepInterview + 参考）
```

## 技术栈
- 底层：**LiveKit**（自托管）+ `@livekit/components-react` 自建房间 + livekit-agents（Python）作为 AI 参与者 + egress 录制
- 过程：借鉴 **DeepInterview** 的 prep→live→post，**计划 + 游标 + 记分卡（无硬状态机）**
- 反馈内核：`missing_slots → what_i_want_to_hear`（参考学长 ProjectProbe 的 `interviewer_os`，仅报告可见）
- 信息：Researcher 中间层（搜索引擎聚合 + 牛客匿名面经 + Tavily + 小红书/知乎[有 cookie 才抓]）→ 结构化岗位画像 JSON
- 语音：全双工（Deepgram zh + ElevenLabs zh + Silero + MultilingualModel），PTT/文字降级
- 语言：LLM 用 DeepSeek（OpenAI 兼容），看屏用 Gemini 视觉

## 开发流程
见 `docs/开发流程-迭代起点.md`。**迭代起点：Phase 1（面试官大脑纯文本闭环 + 双 agent 互聊测试 harness + 离线题库）**，零第三方 key，最快验证差异化。
