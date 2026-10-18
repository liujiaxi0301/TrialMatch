# V2 离线初筛实验

进度：V2P01、V2P02 两份 A 方式回答均已保存，共 10 条源条件通过结构/来源检查，分别引用 23、8 个不同证据 ID。用户确认两例模型和设置一致：Claude Opus 5.5、独立新对话、搜索与 memory 均关闭。见 [两例并排结果](results/two_case_pilot_summary.md)、[V2P01 核查](results/review_V2P01_A.md)和 [V2P02 核查](results/review_V2P02_A.md)。具体客户端及独立工具轨迹未核实，上下文限制仍保留。孕哺条款证据口径待复核，不直接认定为模型错误。新版人工参考标签仍未确认。

**先打开 [RUN_FIRST.md](RUN_FIRST.md)。** 直接上传 [V2P01.json](uploads/A/V2P01.json)，使用 [方式 A 提示词](prompt_A.md)。也可下载 `manual_upload_kit.zip`，里面只有两份上传输入、提示词和操作步骤，不含人工参考答案。

## 已固定的口径

- assessment_date 为 **2021-11-30**，由用户明确选择。reference_date 仍是数据截断日；本场景两者数值一致，不代表实际试验日期。
- 实际筛查、同意书和 V1 日期均为 null。按评估日计算临床初筛；需要真实试验时序的确认仍待补充。
- 新试验为 NCT06774950，完整保留原始 eligibility_text 和 5 条条件。2026-10-11 快照状态为 NOT_YET_RECRUITING，实验不声称历史或当前可招募。
- 初筛状态为 `precheck_status`，不输出最终入组结论或概率。临床资料缺失、医生判断和同意能力评估分别列为后续事项；整条复合条件不拆掉或丢弃。
- “无法作出签署知情同意”是能力要求，不能仅凭没有签署文件判为成立。行政性别也不自动替代孕哺情况的临床评估；相关参考建议尚待复核。
- 本次先做方式 A，输入完整患者和完整条件、关闭搜索。提示词及日期口径与 v1 不同，两个版本不能混合评分。

## 两例

| 案例 | 患者 | 评估日年龄 | 目的 |
| --- | --- | ---: | --- |
| V2P01 | Cleveland | 43 | 核查年龄条件支持、已记录 T2D 病史时长及缺失资料处理 |
| V2P02 | Anthony | 27 | 核查明确年龄冲突，不能因其他条款未知而漏报此冲突 |

上传文件没有附加这些说明或参考标签，患者对象与原始 cohort 处理结果完全相同，包含所有 facts 和来源 ID。本版沿用 cohort 中的 ZIP-member fact ID，可能与 v1 的本地 raw-file fact ID 字符串不同；不可跨版本直接复制证据 ID。

## 参考表和结果

`templates/reference_answers.csv` 有 10 行，当前全部待复核、没有已确认参考标签。`templates/reference_suggestions.csv` 的候选结果为 3 MET、1 NOT_MET、6 UNKNOWN，全部标为未复核建议；它们不是模型结果或已确认 gold。其中“确诊不足 10 年”仅按可核查的已记录诊断日期作初筛解释，不声称掌握真正首次确诊日期。

不必为运行探索性测试先机械确认十遍。正式评分之前须独立复核、固定参考口径；看到模型输出后改变规则时，需另存版本并说明原因。当前没有准确率、系统优越性或正式入组结论。

`results/runs_A.csv` 和 `results/precheck_results_A.csv` 已记录两份用户提交回答及十条模型判断，模型身份及搜索/memory 设置区分用户确认与待确认，同一 run 的 metadata 保留补充历史。原始回答保存至 `results/raw/A/`，每次运行有独立 metadata。`cases.csv` 的状态是材料生成时快照；实际执行进度以 results 为准。结构检查只识别漏条件、错误 ID、伪造日期、排除条款方向和汇总不一致；引用存在不代表推理正确。

## 本地命令

在仓库根目录执行：

```bash
python evaluation/verification/build_v2.py --check
python -m unittest discover -s evaluation/verification/tests -p test_v2.py -v
```

构建器不覆盖已修改的固定输入，保留人工编辑的参考表。v1 的 22 条确认保留在原位置和 `../results/policy_v1_snapshot/`，本次没有修改它们。

拿到**实际模型**完整回答后，记录实际设置，不确定的设置保留 UNKNOWN：

```bash
python evaluation/verification/record_v2.py \
  --pair V2P01 --response /absolute/path/to/response.txt \
  --model '实际模型名称' --model-version '实际版本' --interface '实际界面' \
  --search-enabled FALSE --context-isolation UNKNOWN
```

脚本保留无效 JSON、报错和不完整回答，使用响应哈希和新 run_id 防止覆盖旧结果。搜索及隔离状态是用户报告，不是脚本能独立核实的模型工具轨迹。重复相同记录不会另造一次模型运行；重跑应使用新 run_id。

记录器不会调用模型或修改人工参考答案，导出的结果 CSV 可再生成，不要在其中编辑人工判定。
