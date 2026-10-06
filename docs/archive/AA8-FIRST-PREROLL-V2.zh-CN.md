# AA8 首手真实前滚定位与安全接入建议

只读取已有开发素材元数据并核对PNG SHA256，没有设置人工初始状态。

清单：`G:/PokerSense_private/aa8_first_hand_entry_dense_v2/samples.json`

SHA256：`e0f6812c42bf77b3dde83b194d84cc5a0e87cd87ccbf38b0c94ad1f2c0af30f4`

| 帧 | PTS秒 | PNG SHA256 |
|---|---|---|
|1261|42.033000|3f4d72cfe7e8d4cdde4daa7e6771a71240e7cd8c5d7b2d8b73c2acb8cfc53c5f|
|1262|42.067000|f1e6ba6e7bd9bdbd0f2c765d9d3e097cbebb596dbbe87e73502e864428a568b7|

两帧位于该目录`frames/frame_001261.png`、`frames/frame_001262.png`，
role均development，segment_0000.mkv，local_frame与global_frame一致，
归一化与首手全帧池相同。核对实际文件哈希与清单完全一致。

安全接法：同一个普通V2读取器先依序处理1261、1262，再处理首手1263起的已有
全帧池，使用真实PTS和源审计身份。前滚明确标为非首手owned帧，不修改原首手
边界注册或指标分母；不得人工把手牌/参与名单/现金设为“已知”。若视觉确认
需要多一帧，现有同池1260也可作为真实前滚，不应绕过稳定帧条件。

是否能建立MULTI_POST_DEAL_CANDIDATE必须由正常读数、正向发牌与现金比较
实际决定。若旧现金读数未知，仍保持UNANCHORED，不按参考真值补齐。
