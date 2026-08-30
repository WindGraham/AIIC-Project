# AIIC 项目挑战 · 调研资料库

> 16 小时 AI 模拟面试官项目，调研阶段素材索引。
> 目标：摸清「AI 模拟面试」现有方案的形式与技术栈、以及「面试工具（视频会议 + 现场写代码）」的可复用开源库。

## 目录结构

- `ai-mock-interview/` — 拉取的开源 **AI 模拟面试** 项目（候选练习方向）
- `interview-video-tools/` — 拉取的开源 **面试工具**（视频会议 + 协作代码编辑器 + 在线执行）
- `分析-AI模拟面试方案.md` — 对 ai-mock-interview 各仓库的深入代码级分析（形式/技术栈/闭环/亮点/可复用）
- `分析-AI模拟面试方案-voice组.md` — 语音/LiveKit/本地 LLM 组（Assess-AI / interview-ai-assistant / warmscreen / socratic_mirror / grillkit / Seekr）逐仓库取证
- `ai-mock-interview-analysis.md` — WebRTC/视频/数字人 组（ai-interviewer / Ai-Video-Interviewer / AI-agent-Avatar / ai_mock_interview / InterviewPal / intervio）逐仓库取证
- `分析-面试工具.md` — 对 interview-video-tools 各仓库的深入代码级分析（视频+现场写代码）
- `AI模拟面试方案-形式与市场总览.md` — 交互形式光谱 + 商业三类形态 + 支撑层技术选型
- `未克隆仓库参考.md` — 6 个因网络未能克隆的仓库（web README 摘要）
- `fetch_repos.sh` — 资料拉取脚本（GitHub API 取默认分支 → codeload 下载 tarball）
- `调研总结-选型与MVP建议.md` — **最终汇总**：交互形态取舍、技术栈选型、核心闭环、差异化抓手、10h 执行顺序
- `验收报告-信息与真实感.md` — **独立 subagent 验收**：谁信息最多 / 谁最像真实面试（附 文件:行号 证据 + 对先行结论的 7 条修正）
- `分析-AI模拟面试方案-新增6仓库.md` — 经 mihomo 代理成功拉取后补做的 6 仓库代码分析（含 MockMate 岗位画像 = 差异化核心）
- `调研记录.md`（在 docs/）— 产品初始用户访谈

## 已拉取的开源 AI 模拟面试方案

| # | 仓库 | 形式 | 一句话 |
|---|------|------|--------|
| 1 | heatnan/offerMaster | 语音 | LangGraph+DeepSeek+Whisper+edge-tts，简历+JD 定制、追问、评分、PDF 面评 |
| 2 | ngoanpv/DeepInterview | 语音 | 上传 CV+JD，语音练习，自适应多语言，LiveKit+LangGraph+Next.js |
| 3 | GitHackerz/ai-interviewer | 语音 | WebRTC 实时，ASR/TTS，AI 能听会答 |
| 4 | lhw12138/ai-mock-interview | 语音/文字 | 中文，8 个岗位，自适应追问，多维评分报告 |
| 5 | SatyamPote/Ai-Video-Interviewer | 视频通话模拟 | 模拟视频通话，STT/TTS，岗位动态出题 |
| 6 | troy8chen/ai_mock_interview | 语音 | Next.js+Firebase+VAPI，Gemini 分岗位面试 + 反馈 |
| 7 | mdjamilkashemporosh/Seekr | 语音 | 开源模型本地运行，无专有 API，完全自控 |
| 8 | 20529shanghai/interview-copilot | 语音 | 中文 AI 面试官助手 |
| 9 | Ashmit-Kumar/Assess-AI | 语音 | LiveKit agent（Python），语音+编程测评+自动反馈 |
| 10 | sangh99/interview-ai-assistant | 语音 | LiveKit+LangGraph+RAG 技术面试官 |
| 11 | wildhash/warmscreen | 语音 | 7-agent 反思循环，LiveKit 语音，招募方视角 |
| 12 | ryanreo/intervio | 文字/Whatapp | React+LangGraph+DeepSeek+SQLite，本地 + WhatsApp |
| 13 | GrillKit/grillkit | 语音 | 自托管技术面试训练，语音+实时评分 |
| 14 | weg-9000/AI-agent-Avatar-Interview-Assistant | 数字人 | 多智能体 + 形象化面试官 |
| 15 | krishna684/socratic_mirror | 语音/数字人 | 生物反馈 + 语音 + 3D 头像，Gemini hackathon |
| 16 | HopeLoom/AI-Interview | 文字 | 多 LLM + WebSocket，候选人练习/公司筛选双模式 |
| 17 | fabio-pecora/NextStep.AI | 文字 | Practice→Evaluate→Improve→Track→Repeat 闭环 |
| 18 | linghuashenli65-bit/MockMate | 语音/文字 | 多 Agent + 岗位画像 + 9 阶段流程 + 雷达图复盘 |
| 19 | jennifer88huang/interview-skills | 文字 | JD+简历提示词生成大厂专属面试问题 |

> 以上 19 个 AI mock 仓库 + DeepInterview 均已拉取并做代码级分析（见 `分析-AI模拟面试方案.md`、`分析-AI模拟面试方案-voice组.md`、`ai-mock-interview-analysis.md`）。

## 已拉取的开源面试工具（视频会议 + 现场写代码）

| # | 仓库 | 是什么 | 技术栈 |
|---|------|--------|--------|
| 1 | harshalsakhare2305/Interview4Me | 实时音视频 + 协作代码编辑器 + 在线执行 + 记事本 | MERN + WebRTC/Socket.IO + Monaco |
| 2 | shivam-bhushan/interview_platform1 | WebRTC 视频 + Socket.IO + p2p 代码编辑器 | React/WebRTC/Socket.io |
| 3 | antoniovini47/live-code-interviewer | 实时代码编辑 + 多语言执行 + AI 自动报告 | monaco + SuperViz SDK |
| 4 | marnikitta/livecoding | 极简协作代码编辑器（面试用） | FastAPI + JS |
| 5 | Bhuvanesh3602/TalentIQ-Interview | 视频会议 + 实时代码协作 + 在线执行 | React/Node/MongoDB |
| 6 | humancto/CollabCode | 实时协作代码编辑器 + 多语言 + 在线执行 | Node + Firebase |

> 以上 6 个面试工具均拉取并做代码级分析（见 `分析-面试工具.md`）。

## 商用/行业参考（用于形式分类与定位）
- 北森 AI 面试官（B2B 企业招聘筛选，自研人才科学大模型）
- Final Round AI、Interview Coder、Natively AI（B2C 求职辅助）
- CoderPad / CodeSignal / HackerRank / CodeInterview（技术面试 + 现场写代码）
- 语音层框架：LiveKit / VAPI / Pipecat（全双工实时语音 Agent）

## 说明
- **网络**：GitHub 直连不稳，本机已部署 mihomo 代理（mixed-port `7890`，配置 `/etc/mihomo`）。本仓库下载脚本 `fetch_repos.sh` 通过该代理拉取（`export http_proxy/http_proxy -> http://127.0.0.1:7890`），git 已设全局代理。经此，**全部 22 个仓库均已成功拉取**（16 AI mock + 6 面试工具）。
- 拉取方式：GitHub API 取默认分支 → codeload 下载 tarball。
- 分析文档由并行子代理实读磁盘代码产出并汇总。
