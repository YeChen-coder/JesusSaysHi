# Jesus 写实底图 · Muse 视频素材批次（2026-10-21）

用途：FeatherTalk 口型训练用的说话素材＋两段待机底片。生成服务从 Grok 换成 Muse 网页版（muse.ai，Chrome 里操作）。本文只记 Muse 这条路与 QinChe/Grok 教程不同的地方；预处理、训练、实时接入仍按 `SpecterSaysHi/docs/QinChe-video-generation-and-training-workflow.zh-CN.md` 第 5–10 节，但那些脚本写死了 QinChe 路径和数量，要复制到新目录再改。

## 结果

| 项 | 数量 | 说明 |
| --- | --- | --- |
| 说话素材（选定） | 24 | 训练 22，验证 2（`speech_12`、`speech_36`） |
| 待机底片 | 2 | `idle_waiting`、`idle_listening`，只作推理底片，不进训练 |
| 自动质检通过 | 21 | 其余 5 段头动略超线，按截图人工放行，见 `review/manual_review.json` |
| 需用户判断的人像漂移 | 4 | `speech_05/27/29` 头发偏浅偏暖，`speech_35` 胡子偏灰 |

依据：`delivery_manifest.json`（`selected`、`split`、哈希、质检、人工结论）。不在训练集里的：`native/v1_pilot/`（第一版试生成）、`native/experiments/`（提示词对照）、`native/rejected/`（重生成替换掉的）。

## Muse 原生输出

768×1152（正好 2:3）、H.264 24fps、240 帧、10.000 秒，AAC 单声道 24kHz；抽查未见水印。每段约 1–3 分钟，3 个标签页并发稳定；4 个并发那轮有 2 段回复 "couldn't generate"，原样重试即成功（`generation_failures.json`）。

底图 `reference.png` = `../JESUS_SEA_BASE.png`（SHA256 `5f9057…0e61`），1664×2496；下半脸在 720 宽下约 109px（`review/reference_geometry.json`）。

## 和 Grok 流程不同、必须照做的点

1. **没有参数**：首帧、比例、时长、声线都只能写进提示词。每段新开一个旁聊、重新上传底图，不接上一段。
2. **头必须锁住**：第一版沿用 QinChe 的"自然小动作/看向镜头外"写法，Muse 会大幅转头（转头约 50°、前后 17%）。对照 3 种写法后采用 `prompts/experiments/B_still_photo.txt`：头像靠在头枕上、只有嘴/下巴/眨眼动。待机同理。
3. **台词要填满 10 秒**：原 22 词左右的台词约 7 秒说完，Muse 会把最后半句重复一遍凑时长（提示词写"只说一遍"也没用）。现每句 26–30 词，说话占 0.3–9.3 秒，24 段全部无重复。
4. **下载**：页面的"下载视频"按钮给的是原文件（落到 `Downloads/media-generation-*.mp4`），`ingest.py` 原样移入 `native/` 并记 SHA256、提示词、旁聊链接。

## 质检

- `check.sh <id…>`：离线容器里跑 `check.py`——尺寸/音轨、`head_motion.py` 头动（SCRFD 5 点，9 帧中值平滑后 p5–p95 范围）、Whisper-tiny 全段＋末 3 秒转写查重复。
- 头动门槛：转头 10°、点头 14°、歪头 12°、平移 0.30 眼距、远近 5%。点头/转头读数会被眨眼、眯眼带高，所以略超线的看 0.5 秒间隔头部截图再定。
- **自动质检看不出画面瑕疵**：`idle_listening` 第一版自动通过，但每秒截图里右脸有半透明鬼影，已重生成。新批次必须看 `review/faces_A.jpg`、`faces_B.jpg` 这种逐秒人脸图。
- 口型同步没有自动量化，只在截图上确认嘴在动；需要用户实际播放判断。

## 文件

| 文件 | 内容 |
| --- | --- |
| `build_plan.py` → `generation_plan.json`、`prompts/` | v2 台词与提示词（重跑只覆盖计划和提示词） |
| `generation_results_muse.json` | 每段实际发送的提示词、旁聊链接、原件哈希、元数据 |
| `ingest.py`、`ingest_latest.sh` | 收取最新下载 |
| `check.py`、`check.sh`、`head_motion.py` | 自动质检 |
| `manual.py` → `review/manual_review.json` | 人工结论 |
| `finalize.py` → `delivery_manifest.json` | 交付清单 |
| `review/` | 截图、转写、`qc.json`、`head_motion.json` |
