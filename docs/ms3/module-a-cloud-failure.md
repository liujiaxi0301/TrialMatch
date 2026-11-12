# Module A：云端 checksum 失败验证

**状态：真实云端测试完成，原始证据包独立审核通过（`PASSED`）。**

本次任务为 `xuyang-ms3-hash-20261110t193643z-65e00490`。
已核对故障副本、上传及读回记录、最终 Vertex 状态和 16 条首节点日志。Pipeline 与
`fetch-raw` 按预期失败，日志包含准确文件名的 checksum 异常，后三个节点均为
`NOT_TRIGGERED`，没有开始时间或 executor job。20 项独立证据检查全部通过。
见 [最终证据审核](evidence/module-a/negative-20261110/README.md)。
失败流程图和 checksum 日志截图均已在对话中核对，与原始记录一致。
11 月 12 日已补存[失败流程图原图](evidence/module-a/negative-20261110/02-checksum-failure-test.png)。
单独的 checksum 报错截图尚未归档；准确错误信息已保存在原始 worker 日志中。
三次运行的图片及展示说明见[截图汇总](evidence/module-a/screenshots.md)。

脚本：[verify_checksum_failure.py](../../scripts/ms3/verify_checksum_failure.py)。
使用 Python 标准库及 Cloud Shell 已有的 `gcloud` 登录，不需要安装项目依赖。
本地检查记录：[preflight.json](evidence/module-a/negative-20261110/preflight.json)。

## 验证目标

复用已经审核的成功运行 `trialmatch-data-pipeline-20261110055153`：

- 运行记录的代码版本：`6cae15b387cb4de2e344b49864b68f7d0b24ab6a`。
- 镜像：`workflow@sha256:452cc045ae11c1e42d8f7071cdae565f79e1b57aa9924b3d26c2140ad89a62ad`，
  完整 registry 位于 `us-east1-docker.pkg.dev/trialmatch-ac215-yixiao/trialmatch/`。
- 四节点：`fetch-raw -> process-trials -> validate-data -> retrieve-trials`。
- 项目 `trialmatch-ac215-yixiao`，区域 `us-east1`。

脚本重新读取云端基线，核对成功状态、DAG 指纹、镜像、service account 和输入
manifest 字节指纹。随后创建一个独立测试副本，只给 `raw.dvc` 追加一个换行，
保留 manifest 中原 SHA256。四个节点均关闭缓存。Vertex 中的真实 `fetch-raw`
容器应报：

```text
Checksum mismatch: services/trial_ingestion/data/raw.dvc
```

本次测试针对该固定镜像和四节点配置。当前集成分支 `50dc2ca` 相对该运行版本只改了
README 和前端，pipeline 代码及依赖一致。未来若 B/C 接入后修改了 DAG 或镜像，
这条证据不能自动代表新版本也通过了同样测试。

## 云端操作范围

一次 `run` 新增两个 GCS 对象及一个真实 Vertex PipelineJob，使用现有 service account：

```text
gs://trialmatch-ac215-yixiao-ms3/negative-tests/xuyang/<唯一测试ID>/bad-raw.dvc
gs://trialmatch-ac215-yixiao-ms3/negative-tests/xuyang/<唯一测试ID>/release.json
gs://trialmatch-ac215-yixiao-ms3/negative-tests/xuyang/<唯一测试ID>/pipeline-output/...
```

两个输入对象均以 `ifGenerationMatch=0` 创建，拒绝覆盖已有对象。任务 ID 在提交前
保存，测试产物也使用独立前缀。重复 `run` 会因本地目录已存在而停止。
`collect` 只读取同一次任务，日志查询使用已验证的 `resource.type="ml_job"`。

原数据 release、现有部署和队友的任务不作修改。实际 Vertex 执行会产生普通任务费用。
脚本不包含 commit/push、部署、IAM 修改或资源删除操作。

## 在 Cloud Shell 执行

1. 把 `verify_checksum_failure.py` 上传到 Cloud Shell 主目录。
2. 执行：

```bash
python3 ~/verify_checksum_failure.py run
```

终端会显示唯一任务 ID、Vertex 页面链接和状态变化，最长等待 20 分钟。默认本地目录
是 `~/ms3-negative-20261110/`。脚本不会自动重新提交失败或超时的任务。

完成后下载证据：

```bash
cloudshell download ~/ms3-negative-20261110.tar.gz
```

把压缩包上传到对话中审核，并保存 Vertex 图中首节点失败、后三个节点未执行的截图。

### Cloud Shell 中断或暂时没有日志

读取同一测试的已有任务：

```bash
python3 ~/verify_checksum_failure.py collect
```

不要再次执行 `run`，不要删除已有测试目录。若错误发生在提交前、云端暂时找不到该
任务，或结果为 `INCONCLUSIVE`，先保存终端输出和现有压缩包进行诊断。
历史结果会保留；新一轮收集失败时，当前 `result.json` 不会沿用旧的 `PASSED`。

## 验收条件与结果含义

| 检查 | 通过条件 |
| --- | --- |
| 任务身份与配置 | 新测试 ID、固定镜像、隔离的 release/root、相同四节点 DAG，缓存关闭 |
| 故障副本 | 本地与云端副本一致；仅原 `raw.dvc` 副本改变，期望 SHA256 保持不变 |
| Pipeline / 首节点 | Pipeline 为 `PIPELINE_STATE_FAILED`，`fetch-raw` 为 `FAILED` |
| 错误原因 | 首节点错误或其真实 executor 日志包含上述明确的 checksum 错误 |
| 下游阻断 | 后三个节点均明确为 `SKIPPED` 或 `NOT_TRIGGERED`，且没有执行开始时间或 executor job |

- **Vertex `FAILED` + 脚本 `result.json: PASSED`**：按预期拒绝了错误输入。
- **`INCONCLUSIVE`**：证据不足，或遇到权限、网络、日志延迟等其他问题，不能算通过。
- **脚本 `FAILED`**：观察到错误输入仍让 Pipeline 成功，或下游实际执行等验收不符情况。

如果下游任务元数据缺失，也不会直接推断它们没有执行。
当前账号需要能读取基线、写入测试前缀、提交和查看 Vertex 任务、使用指定 service account
及读取相关日志；脚本不修改权限。

## 证据与范围

压缩包保存计划、基线 API 记录、原始与损坏副本、上传对象信息、提交响应、任务元数据、
首节点日志、验收结果、脚本副本及文件 SHA256 清单。token 只在内存中使用。

这次直接提交已审核的四节点配置，验证真实云端组件的 checksum 拒绝与依赖阻断。
没有调用 Python pipeline runner 或 Docker 部署包装脚本，因此不把旧成功标记清理、
部署拒绝、其他错误输入、训练或正式评估列为这次云端实验的覆盖范围。

## 已完成的本地检查

15 项离线检查通过，包括真实 `cloud.tasks.fetch` 的 checksum 拒绝（存储访问模拟）、
禁止覆盖原对象、关闭缓存、三个下游均纳入判定、错误原因不匹配时不通过、重复运行阻止、
收集不重复提交，以及再次收集失败时避免保留旧通过状态。
Vertex SDK 已接受构造出的 REST 请求格式。所有云 API 调用在本地测试中均被替代。
这些检查不等于云端失败验证已通过，也不是现有 CI 的新增通过项。

在仓库根目录复现离线检查：

```bash
docker/workflow/.venv/bin/python scripts/ms3/test_verify_checksum_failure.py
```

测试使用已经归档的 November 10 证据作为固定 fixture；仅运行云端脚本时不需要这些文件。
