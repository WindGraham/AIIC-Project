# API / 密钥 / 凭据清单

> 汇总开发所需的所有外部服务与凭据。分**必须**（缺了卡对应能力）、**可选**（能跑但更弱）、**登录凭据**、**自托管/免费**（无需申请）四类。环境变量名与 `apps/agent/.env.example`、`apps/web/.env.example` 对齐。

## 1. 必须（请提供；优先级从上到下）

| 能力 | 用途 | 厂商 | 环境变量 | 免费额度 | 备注 |
|---|---|---|---|---|---|
| LLM（核心） | prep 分析 / 出题计划 / live 面试官大脑 / 候选人 agent / Judge / 报告 / Researcher 画像合成 | DeepSeek（OpenAI 兼容） | `LLM_BASE_URL=https://api.deepseek.com`、`LLM_API_KEY`、`LLM_MODEL=deepseek-chat` | 需注册（腾讯/官方） | **Phase 1 就需要** |
| LLM（多模态·看屏） | **"AI 看共享屏幕/截图"**（四技术点之一）＋ 低延迟语音轮 LLM ＋ GeminiTTS 兜底 | Google Gemini | `GEMINI_API_KEY`、`LLM_VISION_MODEL=gemini-2.5-flash` | 有免费额度 | 若只给 DeepSeek（纯文本），AI 无法看屏 |
| STT（语音识别） | 全双工实时转写 + 打断 + 房间字幕 | Deepgram | `DEEPGRAM_API_KEY`、`STT_MODEL=nova-2` | 送 $200 免卡 | 中文走 nova-2 已验证；首小时冒烟 `nova-3` |
| TTS（语音合成） | 面试官语音 | ElevenLabs | `ELEVENLABS_API_KEY`、`TTS_MODEL=eleven_flash_v2_5` | 免费档 | 中文 Good |

## 2. 可选（没有也能跑，但更弱/受限）

| 能力 | 用途 | 厂商 | 环境变量 | 备注 |
|---|---|---|---|---|
| TTS 备选 | 更便宜但中文音质较弱的备选 | Cartesia | `CARTESIA_API_KEY` | Sonic，中文 Limited |
| 视觉备选 | 不用 Gemini 时的看屏 | OpenAI | `OPENAI_API_KEY` | gpt-4o / gpt-4o-mini |
| 搜索第二通道 | 面经/公司检索加一档 | Tavily | `TAVILY_API_KEY` | 免费 1000 credits/月，也可 keyless |
| 录制对象存储 | 分享录制链接用 | S3 / Cloudflare R2 | `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 或 `R2_ACCOUNT_ID`/`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`/`R2_BUCKET` | 也可用自托管静态目录，无需 key |
| 数据库 | 跨页持久化 | Supabase | `SUPABASE_URL`/`SUPABASE_ANON_KEY` | 也可用 agent API 内存/SQLite，无 key |

## 3. 登录凭据（小红书/知乎，已确认必加）

| 平台 | 环境变量 | 说明 |
|---|---|---|
| 小红书 | `XHS_COOKIE` | 走官方 MCP：有 cookie 才抓、失败自动降级、有缓存 |
| 知乎 | `ZHIHU_D_COOKIE` | 搜索需 `d_c0` cookie；MCP 接入；失败自动降级 |

## 4. 自托管 / 免费（无需申请，已就位或用免费件）

| 能力 | 说明 |
|---|---|
| LiveKit 服务器 | 自托管（本机 :7880），key/secret 在 `/data/livekit/config/egress.yaml`；视频/语音/共享屏幕/房间全靠它，**无需 LiveKit 云 key** |
| 录制 | egress v1.8.0 输出本地 `/data/livekit/recordings`（免费）；分享由 web 提供或走第 2 节 S3/R2 |
| 搜索引擎聚合 | MockMate 360/bing/baidu HTML 抓取，零 key |
| 牛客匿名面经 | 匿名 API，无需登录，低风险 |
| Tavily keyless | 免费无 key（限速） |
| 代码执行 Piston | 本地容器或公共 emkc.org，无 key |
| 转写降级 | 本地 faster-whisper / speaches（无 key，批量、无实时） |

## 5. 最低可跑组合（无这些也能演示）

- **纯文字闭环**：只需 **LLM key（DeepSeek）** → 跑 prep→live→post ＋ 双 agent 互聊 harness ＋ 报告。
- **加语音全双工**：再加 **Deepgram + ElevenLabs**（＋ Gemini 可看屏/低延迟语音轮）。
- **加共享屏幕读屏**：加 **Gemini（视觉）**。

> 提示：`GEMINI_API_KEY` 一键同时满足「看屏（视觉）＋ GeminiTTS 兜底 ＋ 低延迟语音轮 LLM」，性价比最高，建议优先申请。
