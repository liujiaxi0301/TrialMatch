# Cleveland 数据缺失来源核对

2026-10-18 对照当前患者原始 FHIR 与完整处理结果。核对对象是本轮 V01–V03 共用的合成患者，不代表整个 Synthea 数据集。

| 资源/事实类型 | 原始 FHIR 条数 | 处理后条数 |
| --- | ---: | ---: |
| Condition / conditions | 24 | 24 |
| Observation / observations | 147 | 147 |
| Procedure / procedures | 39 | 39 |
| MedicationRequest / medications.requests | 5 | 5 |
| MedicationAdministration / administrations | 0 | 0 |
| MedicationDispense / dispenses | 0 | 0 |
| MedicationStatement / statements | 0 | 0 |

以上四类实际存在的临床资源，处理器检查的事件日期均未晚于 reference_date；最后记录日期均在 2020-12-28。这些事实没有因参考日期过滤而减少。原始 Bundle 也没有 Consent 或 ResearchSubject 类型资源；这只说明缺少这两类专用资源，不足以单凭资源类型断言所有其他字段都绝不含相关文字。

需要区分以下原因：

1. **当前导出样本没有对应证据。** 有处方而无给药、发药或用药陈述，不能据此确认实际服药、稳定剂量或依从性。某疾病未记录，也不等于导出文件提供了明确的阴性病史。不能从单个样本推断 Synthea 整体不支持某类记录。
2. **试验工作流资料不在这份普通合成病历中。** 真实试验的同意书、参加意愿、筛查或 V1 日期不能凭普通就诊记录自行补全。患者样本来自 2021 年归档，临床事件在 2020 年结束，试验快照为 2026 年。
3. **有数据，但评估口径使整条仍为 UNKNOWN。** 出生日期和 reference_date 年龄已知；HbA1c、BMI、血压也有历史测量。本轮用户确认不以 reference_date 代替实际试验日期，因此这些数据不一定足以确认试验时点的条件。此类 UNKNOWN 不能描述成 Synthea 未生成年龄或检验数据。
4. **当前提取范围有限。** 原始 Bundle 的 Encounter、DiagnosticReport、DocumentReference、CarePlan 等没有作为独立 facts 输出，计入 `unprocessed_resource_types`。本次核对证实上述核心资源数量完整，不等于已审计所有其他资源内容。若某条要求可能依赖这些内容，需要回查原始文件后再判断。

当前结论是“给定病历证据不足以证明该条件”，不等于患者真实存在或不存在某种疾病，也不等于模型无法理解条件。后续 A/B 报告应分开说明原始数据缺失、提取范围、未知试验日期及模型推理问题。
