# AA8 独立评估编排补充层

两个新模块均在基础候选冻结后、保留集预测前创建，必须如实记录这条时间线。
没有修改已有冻结文件，没有更改模型、阈值、模板或归一化参数，没有放宽原边界
采样器的3秒密集提取限制。本层没有CLI，只有显式授权后调用的函数。

## 两阶段补充冻结

1. 提取前生成独立不可变supplement JSON，字段：
   `base_freeze_sha256`、`frozen_at_utc`、`dataset_harness_sha256`、
   `evaluation_harness_sha256`、`registry_sha256`、`normalization_sha256`、
   `audit_index_sha256`。冻结时间必须晚于基础冻结、早于实际调用。
2. `aa8_holdout_dataset.extract`验证原冻结、审核索引、完整手注册、同源审计、
   原开发样本归一化哈希，然后只输出完整手及最多30帧前滚，保持role=holdout。
   只有此明确调用才打开源录像；导入和元数据测试不会打开图像或设备。
3. 数据集生成后，新建另一个不可变预测supplement，保留base/harness/registry
   绑定并加入`target_manifest_sha256`；不能回写或回填提取前的supplement。
4. `aa8_holdout_predict.predict_rows`验证所有绑定，保存真实prediction_start_utc，
   输出逐帧原始候选、13字段评估映射与输出哈希，不宣称视觉通过。

## 编排等价和字段边界

FrozenPredictionState显式复制原aa8_visual_pipeline的组件初始化和逐帧编排，
保留原组件类、参数与判断顺序，不使用AST或exec，不篡改development inventory。
根任务应在原开发帧上做编排等价回归，再冻结本新层并授权保留集处理。

只有原读取器确认的视觉候选才映射KNOWN。UNKNOWN动作链、完整参与状态、
平台手牌ID、确切街/结算状态、蘑菇与暴击触发保持UNKNOWN；规则文案或计数
不能当成触发，空下注不得填零。`strategy_eligible`始终false。

读取注册元数据后，只做索引检查确认本批应为18783–23924，共5142帧，
完整手的5131帧加首手前滚11帧。此检查没有读取任何保留集图像或运行预测。
原注册JSON未修改；生成的数据清单反向记录其SHA256。提取后对覆盖到的已审
边界见证PNG哈希复核；源文件尺寸/mtime在解码前后检查，原SHA256审计保留。

13项元数据/拒识契约测试通过。保留集的实际提取、预测与比较必须由后续明确
调度触发，本交付不包含这些执行，也不预先声称任何保留集准确率。
