# AA8 当前帧牌面候选

2026-09-09。新增 `tools/aa8_cards.py`，未修改旧九座组合读取器的布局保护。

接口：`AA8CardReader(heads).read(image, frame, pts, source)`。
`pts` 使用录像秒数而非墙上时间。heads可传已有模型对象或路径。
模型复用 `configs/vision/wepoker_android_capture_card/card_heads.npz`，
rank_floor=0.5、suit_floor=0.3，与现有 AA 组合读取器相同；没有重新训练或下调。
后续增加显式 `preprocessing="gaussian_050"` 候选选项，默认None不变，
详情见 `AA8-CARD-PREFLIGHT.zh-CN.md`；下文v2仍为未启用预处理的历史基线。

## 当前帧与连续性保护

- Hero和公共牌必须具有正向牌面背景与上边界支持。
- 公共牌结算上浮采用既有最多20像素的唯一边界搜索，不依据预测牌面选位置。
- 模型融合至少3帧，随后相邻两次同一结果确认；缺失立即清空，不借未来亮牌补过去。
- 来源切换、断帧、时间回退/不增加或超过1秒重置；同源重复/倒退帧拒绝并清空。
- ROI变化、牌面消失、模型拒识不会复用旧牌；Hero与公共牌重复身份时全部拒识。
- 返回牌面均是候选，`strategy_eligible=false`、`model_calibrated_for_aa8=false`。

## 实际开发录像结果

证据：`G:/PokerSense_private/aa8_cards_probe_v2/report.json`，9个窗口各5帧，共45帧。
模型、实现、源清单及逐帧SHA256均记录；未读取保留集、未打开设备。

| 窗口最后帧 | Hero | 公共牌 |
|---|---|---|
|1474、1984|UNKNOWN|均未识别出牌；无牌不自动认定为preflop|
|2074、2404|5d6d|5h6c6s|
|2824|5d6d|5h6c6sTc|
|3064、3184|5d6d|5h6c6sTc3d|
|4894|9dQd（已弃牌变暗）|7h5h2sTc|
|4954|9dQd（已弃牌变暗）|7h5h2sTc9c（部分牌上浮）|

1474和1984的6d模型得分约0.49515，低于0.5，因此Hero整体拒识。
这是已发现的真实缺口，没有把之后看清的6d回填，也没有降低门槛强行通过。
该45帧结果只用于开发诊断，不能表示整段录像准确率或独立验收。

15项单元契约测试通过，flake8通过。测试覆盖时间/帧连续性、缺失清理、
跨区域重复牌、来源切换等代码性质；模型真实表现以上述录像证据为准。
