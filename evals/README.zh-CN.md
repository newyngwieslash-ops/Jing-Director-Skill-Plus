# JingStudio 4.5：离线行为评估证据层

## 当前状态与边界

**当前真实模型行为评估：`not_run`；真实视频质量：未验证。**

`cases.json` 为本项目独立撰写的 20 个用例、60 条输出行为断言。借鉴 DirectorSKILL 固定提交 `c65ae0d14457053efb1e354c7e7f7e120d97fad1` 的生成/评分分离、逐断言证据、硬失败和聚合门槛方法；没有复制其 57 个用例，也没有导入其删镜、拆镜等冲突规则。上游定位：`evals/run.md`、`evals/evals.json`。第三方许可信息见项目根目录通知。

本工具不调用模型，不自动回答用例，不替人判断导演语义，不认证模型版本、评分独立性或视频质量。单元测试只验证离线证据绑定和门槛计算。测试中的文字与评分是明确标记的 **synthetic fixture**，绝不能累计为真实模型运行数。

新方法脚本 `director_methods.py scaffold/validate/review` 的结构校验与本层互不替代：`structurally_valid` 不是艺术审批；本层文本人工评分也不能放行生产合同、原有空间图门禁或成片。

## 1. 只校验用例；不算跑过模型

在项目根目录执行：

```sh
python scripts/director_behavior_evals.py validate-cases --suite evals/cases.json
python scripts/director_behavior_evals.py evaluate --suite evals/cases.json --root . --out evals/my-not-run.json
```

第二条生成 `not_run` 报告并返回退出码 1。这是正确的未运行状态，不是评估失败已发生。`baseline-not-run.json` 为本次版本交付的未运行状态说明。

## 2. 独立生成、保存原始响应，再记录

1. 冻结待测版本及用例文件；准备只读源快照（例如 SKILL、加载的规则文件、合同、批准记录）。源文件随记录保存，不能仅用“4.5”标签代替证据。
2. 每个用例使用全新生成会话，输入 `prompt` 原文，不注入评分断言，不沿用先前镜头上下文。保存完整输出，包括前言、拒绝、工具结果及失败信息，不能裁剪成看似正确的片段。
3. 在授权范围外的付费生成或服务调用，需要另行授权；本工具不执行这些动作。
4. 独立评分会话/人工审核人员在生成完成后再看断言。对同一被测版本反复采样时，分别保存 run，不能只挑通过的响应冒充全套结果。

建立专用目录 `evals/runs/my-run/`，放入 `source/SKILL.md` 等源文件快照和 `responses/<case-id>.txt`。所有 artifact 路径相对于 `--root`，必须在该根内，拒绝绝对路径、`..`、反斜杠、符号链接。单文件上限 2 MiB、列表上限 200、单例最多 20 条断言。

`record-input.json` 格式如下（仅展示一个用例，因此最终一定是 incomplete）：

```json
{
  "run_id": "my-run",
  "run_kind": "provided_model_run",
  "model_label": "填写实际自报模型版本与运行日期，不确定则写unknown",
  "sources": ["source/SKILL.md"],
  "responses": [
    {
      "case_id": "single-prompt-scope",
      "path": "responses/single-prompt-scope.txt",
      "generator_session": "generation-case-01"
    }
  ]
}
```

```sh
python scripts/director_behavior_evals.py record --suite evals/cases.json --root evals/runs/my-run --input evals/runs/my-run/record-input.json --out evals/runs/my-run/run.json
```

`record` 只对**已有响应**做记录。`run_kind` 只能是 `provided_model_run` 或 `synthetic_fixture`；手写模拟响应必须用后者。提供者仍对来源真实性负责，标签不是密码学证明。

记录包含：用例文件原始字节 SHA-256、每例 prompt 的 UTF-8 SHA-256、源快照文件和响应文件原始字节 SHA-256。空响应、重复用例、重复生成会话 ID、未知用例会阻断。**prompt 哈希绑定预期输入，不能证明远端实际输入过该文本；源哈希只证明所列文件，不能证明未列出的文件或真实工具读取行为。** 实际输入、模型版本和文件读取事实应另保存可信运行日志；此版本不验证日志真实性。

## 3. 人工评分文件

`grades.json` 顶层必须为以下结构。每例每条断言给出 pass/fail、完整响应中的精确引用和审核理由。`run_sha256` 是 `run.json` 解析后以本脚本 `encoded()` 规范化的 SHA-256，不是排版后的 JSON 文件字节哈希；可通过下面命令取得：

```sh
python -c "import sys;sys.path.insert(0,'scripts');import director_behavior_evals as e;print(e.sha(e.encoded(e.load('evals/runs/my-run/run.json'))))"
```

```json
{
  "schema_version": "1.0",
  "run_sha256": "替换为上述摘要",
  "reviewer_id": "人工审核者标识",
  "grader_session": "grading-session-01",
  "manual_review_acknowledged": true,
  "grades": [
    {
      "case_id": "single-prompt-scope",
      "response_sha256": "替换为run.json中该响应的artifact.sha256",
      "assertions": [
        {
          "id": "a1",
          "verdict": "pass",
          "quotes": ["替换为响应中确实存在的逐字引文"],
          "rationale": "人工解释该引文为何满足此断言，并核查全文是否有矛盾"
        }
      ]
    }
  ]
}
```

这只是**格式示意，不能直接作为真实评分**。未人工完成检查时使用 `manual_review_acknowledged:false`，工具将阻断，而不是把草稿当评分通过。

- `presence` / `judgment` 的 pass 必须至少有一条原文引文；不存在的引文阻断整个评估。
- `absence` 要人工阅读全文；其 pass 可空引文，但必须有审核理由。一个局部引用不能证明全文没有违规内容。
- fail 可无引文（例如要求的内容缺失），但必须解释原因。只验证引文“存在”，**不验证其相关性、充分性或结论真伪**。
- 评分会话 ID 必须不同于所有生成会话；生成会话每例不同。这只能检查自报字段，不能认证真正隔离，也不应由同一生成上下文自评后假装盲评。
- 缺例、缺评分、缺断言均是 `incomplete`；重复用例、重复断言、过期摘要、伪造引文均阻断。

```sh
python scripts/director_behavior_evals.py evaluate --suite evals/cases.json --root evals/runs/my-run --run evals/runs/my-run/run.json --grades evals/runs/my-run/grades.json --out evals/runs/my-run/report.json
```

重新评估会核对所有源/响应文件与 prompt/suite 绑定；即使只修改用例文件空白也需要重新记录，不得复用旧哈希。所有写入采用独占创建，拒绝覆盖已有输出；新轮次使用新文件/目录。

## 4. 门槛与返回值

每例所有断言通过才算该例通过。门槛为 `ceil(例数 × 百分比 / 100)`：当前 20 例、92% 要至少 **19 例**通过；57 例、92% 应为 **53**，不是 52。所有 `hard_fail:true` 例必须通过，总分不能抵消其失败。缺任何应评内容时不会给 complete pass。

| status | 含义 | CLI 退出码 |
|---|---|---|
| `cases_valid_not_run` | 用例结构有效，尚未运行 | 0 |
| `not_run` | 没有提供响应运行记录 | 1 |
| `incomplete` | 响应/评分/断言未齐 | 1 |
| `manual_grades_pass` / `manual_grades_fail` | 所提供模型响应的人工评分结构通过校验，门槛达标/未达标 | 0 / 1 |
| `synthetic_fixture_pass` / `synthetic_fixture_fail` | 合成fixture的评分/绑定机制检查结果，不是真实模型成绩 | 0 / 1 |
| `evaluation blocked`（stderr） | 无效字段、过期证据、路径、资源或覆盖错误；不写成功报告 | 2 |

报告始终声明 `release_ready:false`、`production_evidence:false`、`video_quality_verified:false`、`semantic_correctness_verified:false`、`model_identity_verified:false`。`provided_model_response_evidence` 只表示提供者标为模型运行且材料齐备，不是独立认证。任何系统都不得把退出码 0 单独用作真实模型/视频/生产放行信号。

## 5. 本地机械回归

```sh
python -m unittest discover -s tests -p test_behavior_evals.py -v
```

回归覆盖 ceil 边界、硬失败、缺项/重复、过期 suite/prompt/source/response/grade 哈希、伪引文、评分隔离字段、未运行、合成fixture、路径/资源与防覆盖。它不替代真实独立模型行为评估或视觉验收。
