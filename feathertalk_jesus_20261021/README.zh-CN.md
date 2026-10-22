# Jesus FeatherTalk 训练（2026-10-21）

素材：`../Jesus_material/muse_video_20261021/`（Muse 生成，24 段说话＝训练 22＋验证 2，两段待机只作底片）。本目录是独立工程，只读挂载 SpecterSaysHi 的 FeatherTalk 上游代码与镜像 `feathertalk-lab:local`，不写 SpecterSaysHi。

## 用户要求

- 训练 150 轮，挑最好的一轮。
- **往后看的音频只能 100ms 以内**（不用 balanced 的 400ms）。

## 和 QinChe 配方的唯一实质区别：训练就按 80ms 实时窗口

FeatherTalk 每帧读 20 帧音频窗口（前 10、当前、后 9）。QinChe 用全片特征训练、实时却用 fast（后 9 帧补零），训练和推理对不上。这里两边用同一份代码 `jesus_stream.py`：

- 实时只往后多等 **2 帧＝80ms**（`LOOKAHEAD=2`），窗口里 i+3 以后**一律置零**，即使音频已经到了；
- 音频编码器只看「最多 4 秒历史＋到 i+2 帧末尾＋80 采样」，和实时会话完全一样；
- `prepare_stream.py` 为每一帧按这个规则单独编码（同一批里早渲染的帧多看到 1～2 帧音频，所以另存 audio_lookahead=4 的版本，训练时 60%/40% 随机取）。

其余与 QinChe 认可配方一致：随机初始化、FP32、8 对相邻帧、随机训练帧作参考、同样的 loss 权重。学习率 1e-3（1–60）、3e-4（61–110）、1e-4（111–150）；每 5 轮验证，50 轮起每 5 轮存档；`last.pth` 可断点续训。

## 流程与入口

```text
docker compose run --rm worker python -u /clean/pipeline.py
  prepare.py         24 段 → 25fps、JPEG95→110 点→144 裁切、嘴部掩码、16k 音频
  prepare_stream.py  每帧流式音频窗口（只存 i-10..i+2 共 13 行，fp16）
  train_jesus.py     150 轮
  prepare_dynamic.py 两段待机：250 唯一帧、498 帧往返
  evaluate.py        每个存档在验证集上：嘴部 L1＋口型同步（嘴部暗度与原片的相关和时延）；
                     最好 3 个＋最后一轮走实时路径导出视频（100ms 分包、80ms 往后看）
package_assets.py <epoch> <idle>   打包到 ../avatar_assets/jesus_20261021（含 BT.709 待机视频、release.json 哈希）
register_character.py              把 jesus 写进 ../avatar/characters.json
realtime_check.py <24k pcm>        对运行中的头像服务按墙钟 100ms 推流，测首帧、帧数、打断
```

## 接入 JesusSaysHi

`avatar/` 新增实时模式 `stream80`（`stream_core.MODES`、`realtime_session.py` 置零 i+2 以后、`server.py` 接受该模式）。启动：

```dotenv
JESUS_AVATAR_ENABLED=true
JESUS_AVATAR_CHARACTER=jesus
JESUS_AVATAR_MODE=stream80
JESUS_AVATAR_ASSETS=C:\Users\yeche\Desktop\CodexRelatedProject\JesusSaysHi\avatar_assets\jesus_20261021
```

`docker compose --env-file config.local.env up -d --build --wait avatar`

## 结果（2026-10-22）

150 轮完整跑完，每轮约 44 秒。**选定第 60 轮**（`checkpoints/epoch_60.pth`，SHA256 `b7a59aee…2686d`），第 150 轮留作备选。依据见 `output/selection.json`、`output/evaluation.json`、`output/amplitude.json`。

| 轮次 | 嘴部 L1 | 口型同步 r（两段验证平均，时延 0） | 嘴部开合幅度 / 原片（12 / 36） |
| --- | --- | --- | --- |
| 50 | 0.0392 | 0.834 | 0.893 / 0.891 |
| 60 | 0.0400 | 0.852 | 0.909 / 0.854 |
| 70 | 0.0392 | 0.825 | 0.865 / 0.876 |
| 75 | 0.0393 | 0.815 | 0.865 / 0.903 |
| 100 | 0.0395 | 0.809 | 0.857 / 0.907 |
| 125 | 0.0395 | 0.814 | 0.859 / 0.909 |
| 150 | 0.0396 | 0.809 | 0.843 / 0.911 |

- **所有存档的最佳时延都是 0 帧**：只往后看 80ms 没有造成嘴型慢于声音。
- 验证 L1 从第 30 轮起基本不动（0.039–0.040），训练 loss 一直降，后期主要是拟合训练片；第 60 轮同步最好、开合幅度在 speech_12 上最好、抖动与其他轮相同，所以选它。只有 2 段验证，差距小，故保留 150 作备选。
- 画面：嘴部合成无接缝，颜色与胡须衔接自然；生成的嘴比原片**偏保守**（"o"口型不够圆、开口略小、牙齿和唇纹偏软），这是 144×144 输出的上限，不是同步问题。对照图 `output/strip_speech_12.jpg`、`output/strip_speech_36.jpg`。
- 导出视频（实时路径，100ms 分包、80ms 往后看）：`output/eval/epoch_60/`（speech_12、speech_36 两段验证＋novel 一段没见过的声音）；50/70/75/150 也在 `output/eval/`。

## 实时实测（JesusSaysHi 头像服务，jesus／stream80，显卡空闲时）

| 指标 | 第 1 次 | 第 2 次 |
| --- | --- | --- |
| 首帧（第一包音频发出→首帧到达） | 214ms | 157ms |
| 10 秒语音出帧 | 250/251 | 250/251 |
| 音频结束→最后一帧 | 203ms | 267ms |
| 打断→回待机 | 4ms | 6ms |
| 打断后再说话首帧 | 146ms | 142ms |

- 首帧比 fast 多约一包：第 0 帧需要到第 2 帧末尾的音频（约 125ms），100ms 分包下要等第二包。
- 结尾约 200ms 来自服务端「0.24 秒无新音频才收尾」的既有逻辑（最后 2 帧在收尾时补齐），不是模型问题。
- 训练进行中测的一次（`realtime_check_epoch10.json`）因与训练抢 GPU，结尾晚 1 秒，不作数。

## 已知问题

1. 嘴型偏保守、细节偏软（见上）。要更好需要更高分辨率的模型或更多「大开口」素材，不是续训能解决的。
2. 结尾收尾等待约 200ms；若要更快，可让语音端在每句结束时发显式结束信号，替代 0.24 秒静默判断。
3. 人像漂移的 4 段素材（speech_05/27/29 头发偏浅偏暖、speech_35 胡子偏灰）都进了训练；目前没看出模型颜色跑偏（嘴部颜色由 NativeFaceMatch 按底片校正）。

## 2026-10-22 补充：眨眼过快 → 重排待机时间线

用户反馈待机眨眼太快。实测 idle_waiting 原片 10 秒眨 7 次（约 42 次/分钟，正常静息 15–20）。用加了「10 秒只慢眨 2–3 次」的提示词在 Muse 重生成 3 段：1 段被拒、1 段仍眨 7 次、1 段变成长时间半闭眼，都不能用（`Jesus_material/.../native/experiments/idle_waiting_v3_take*`）。

改为不重新生成：运行时按 `source_indices` 时间线取底片帧，`slow_blink_timeline.py` 在 14–178 帧内逐帧（±1，无跳切）往返行走，只在到期时穿过 48–56、83–96、147–151 三处眨眼，否则在眨眼前一帧折返；整体再做往返镜像成 612 帧（24.5 秒）循环。结果 6 次眨眼、14.7 次/分钟，用 `blink_check.py` 对渲染出的视频独立复核一致。已打包为 `idle_waiting_slowblink` 并上线（release `20261021-muse-epoch60-idle_waiting_slowblink`），实时复测首帧 224ms、250/251 帧、打断 10ms。

同日排查「嘴抽」：旧的音频特征平滑（α=0.5/0.3）在本模型上抽动只降 0–3%，隔帧生成反而增 15–20%，未采用；中英文抖动相同；浏览器无丢帧。主要怀疑是画面比实际听到的声音晚约 150–250ms（语音端先播放再转发给头像），对照视频 `output/ab/eval/epoch_60/AB_sync_vs_late_*.mp4`，待用户确认。

## 2026-10-22 补充：嘴「抽」的真正原因 → 固定模型参考帧

用户确认：嘴和声音对齐的版本也在抽，问题是嘴形变化太快。按嘴部整块的时间频谱测（`mouth_spectrum.py`：嘴部区域 PCA 前 8 个分量，6 Hz 以上能量占比）：

| | 6 Hz 以上占比 |
| --- | --- |
| 真实素材 | 2.5–3.9%（一段 6.3%） |
| 原实时：模型每帧用当前底片当参考 | 6.0–7.0% |
| 固定参考帧 | 1.6–2.0% |
| 固定参考帧＋音频特征 EMA 0.5 | 0.7–1.0%（可能偏钝，未采用） |

原因：底片每帧都在变（眨眼、呼吸、往返时间线），模型参考输入随之变，生成的嘴就跟着高频变化。处理：`avatar/engine/native_loop_core.py` 新增可选 `settings.model_reference_frame`，Jesus 设为唯一帧 120（睁眼闭嘴）；合成仍贴在当前动态底片上。gentleman 不受影响。上线后实时复测首帧 238ms、250/251 帧、打断 14ms；JesusSaysHi 50 项测试通过。对照：`output/AB_reference_{zh,en}.mp4`。

## 2026-10-22 最终选择：底片放慢 1.5 倍（用户选 ③）

用户要求先放慢底片再比较。`prepare_idle_variant.py` 处理 ffmpeg minterpolate（mci 运动插帧）放慢的 idle_waiting：1.3 倍 323 帧、1.5 倍 372 帧。四版同屏对照（`output/COMPARE4_{zh,en}.mp4`）：① 正常速度少眨眼时间线＋固定参考帧；② 放慢 1.3 倍、参考随底片；③ 放慢 1.5 倍、参考随底片；④ 放慢 1.3 倍＋固定参考帧。6 Hz 以上占比分别约 1.6–2.0%、5.4–6.2%、4.6–5.3%、1.6–2.0%（指标上固定参考帧最有效），但**用户看下来 ③ 综合效果最好**，按 ③ 上线：release `20261021-muse-epoch60-idle_waiting_slow15`，742 帧（29.7 秒）往返循环，眨眼约 28 次/分钟，`register_character.py` 不加 `--reference`（参考随底片）。实时复测首帧 144–243ms、250/251 帧、回待机 200–290ms、打断 11ms。
