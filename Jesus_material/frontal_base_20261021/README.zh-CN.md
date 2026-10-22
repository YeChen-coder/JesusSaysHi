# 耶稣正脸底图候选 · 2026-10-21

用途：FeatherTalk 人物底图，在 Muse 上以此图生成视频。人物参考统一为 `source_reference.png`（= `../Jesus_base_two.png`），Grok Imagine image_edit，每张独立从参考图编辑，原生 832×1248 JPEG，未二次编辑。

尺寸口径：FeatherTalk 官方 110 点检测 + compute_face_bbox 的下半脸框宽度，换算到 720 宽视频。模型输出 144×144，视频里该区域超过 144px 就得放大回贴，会变糊，所以要小于 144。参照：秦彻新底图 `reference.jpg` 16.1% → 116px（效果好）；Gentleman 底图 20.6% → 148px（视频中约 158px）。

| 轮次 | 文件 | 占画宽 | 720 宽下 | 结论 |
| --- | --- | --- | --- | --- |
| 1 | A_olive_grove.jpg | 20.4% | 147px | 偏大，不用 |
| 1 | B_galilee_shore.jpg | 19.6% | 141px | 偏大，不用 |
| 1 | C_stone_courtyard.jpg | 21.5% | 155px | 偏大，不用 |
| 2 | A2_olive_grove.jpg | 14.1% | 101px | 可用，略小 |
| 2 | B2_galilee_shore.jpg | 17.3% | 125px | 可用；水面背景在视频里可能闪动 |
| 2 | C2_stone_courtyard.jpg | 15.0% | 108px | 可用 |

记录：`*.prompt.txt`、`generation_results.json`（第1轮）、`generation_results_round2.json`、`screening.json`（第1轮）、`screening_round2.json`。尺寸测量不代表相似度，人物和观感由用户确认。

## 第3轮（加利利湖边，补全双手、提高清晰度）

用户反馈：A2 没手不能用；B2 背景好，但手不全、清晰度一般。B3a、B3b 为同一提示词从 `source_reference.png` 独立生成两次；B3c 从 B2 二次编辑。

| 文件 | 占画宽 | 720 宽下 | 嘴部清晰度（同尺度拉普拉斯方差，B2=121） | 双手 | 结论 |
| --- | --- | --- | --- | --- | --- |
| B3a_galilee.jpg | 15.3% | 110px | 112 | 完整，五指正常 | 可用 |
| B3b_galilee.jpg | 15.1% | 109px | 159 | 完整，五指正常 | **推荐** |
| B3c_from_B2.jpg | 15.0% | 108px | 85 | 完整，五指正常 | 二次编辑变糊，不推荐 |

Grok Imagine 原生输出上限为 832×1248，本轮未做放大处理。记录：`generation_results_round3.json`、`screening_round3.json`。
