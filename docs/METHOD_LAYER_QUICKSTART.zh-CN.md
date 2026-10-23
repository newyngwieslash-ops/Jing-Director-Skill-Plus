# 4.5 方法层快速上手

目标：在4.4保真、逐镜空间覆盖、角色标识和交付主干上增加方法旁挂包。原Contract仍为3.0.0；新方法包schema为1.0.0。没有新供应商API、自动剪辑/混音或真实模型调用。

## 1. 选项目与范围

使用你实际批准的合同，保留独立来源、角色roster、空间包及身份登记。以下使用随包镜9草稿演示，**不是用户生产项目已批准**。在技能包根目录运行；输出应放作品项目，不放安装目录。命令使用Python3.10+，只生成离线文件，不联网。

```bash
python scripts/director_methods.py scaffold --contract examples/hall-shot-09/director-contract.json --out /tmp/jingstudio-method-demo --fps 24
python scripts/director_methods.py validate --contract examples/hall-shot-09/director-contract.json --pack /tmp/jingstudio-method-demo/method-pack.json
python scripts/director_methods.py review --contract examples/hall-shot-09/director-contract.json --pack /tmp/jingstudio-method-demo/method-pack.json --out /tmp/jingstudio-method-review
```

Windows把 `/tmp/...` 换成项目内尚未使用的绝对路径。scaffold/review要求新建或空输出目录，勿指向已有交付目录。可给validate增加 `--report <新文件路径>` 保存检查报告。

## 2. 填写而不是伪造完成

- scaffold从合同提取镜号、角色引用和锁定快照，生成六部门director_book、逐镜performance/repair/capability/sound/edit和change_requests。
- 保留contract_sha256与locked_source；不手工改快照绕过校验。合同变更后重新生成并审查受影响方法内容。
- 部门camera/lighting/color/performance/editing/sound各有rules；只给本次涉及镜添加规则。结构以 `schemas/director-method-pack.schema.json` 为准。
- 备注classification为source/inference/unknown。source的text必须等于evidence所指合同字符串的精确引文，不能把推断贴成原文；该检查仍不认证独立原文真实性。
- role_ids引用合同subjects，可包含群体ID；它**不是**逐人名册覆盖证据。展厅六个subject仍需既有roster展开为十人。
- 预算按attempt units记录，不是货币额度；V2V消耗总单位但不计同设计失败strike。人工费用/凭证用工作单补充，不能声称CLI审计了实际账单。
- capability是人工规划声明；代码不访问或验证证据链接，能力枚举为unknown/supported/unsupported；supported只是有记录的人工声明，不等同实际供应商测试。所有输出execution_ready=false。
- DIALOGUE cue需保留原字、说话人、起止帧和画内/画外/旁白性质。不要为避免口型问题改对白模式。
- edit记录的是合同映射与计划，不是已读到的媒体入出点。完整制作三时基和handles先在工作单记录，当前工具不导出NLE、不探测真实素材。
- 变更提议放非激活change_requests，不伪装成已执行修复；任何改镜仍走原批准流程。

按需读取[方法入口](../references/director-method-layer.md)及[人工工作单](../templates/director-method-worksheet.md)。不要将整个上游YAML复制进合同。

## 3. 正确解读结果

`structurally_valid=true`与退出码0只表示结构检查满足；报告仍可能有blockers。`status=draft`不表示生产就绪；`execution_ready=false`、`artistic_approval=false`始终保留。`SOURCE_BASELINE_NOT_AUTHENTICATED`说明合同摘要不是独立原文证明。review为离线可读审阅输出，不产生批准证据。

如果缺场/镜/角色、来源不符、角色图标识/图件/哈希失效，仍用原有流程阻断；方法包不能豁免它们。scaffold示例的unknown和待补内容是诚实草稿，不应填假证据追求全绿。

## 4. 评估与交付

行为用例的组织、离线证据和运行命令见[评估说明](../evals/README.zh-CN.md)。合成夹具测试不等于真实模型评测，更不证明真人感或最终视频质量。实际验收结果以本包[测试报告](TEST_REPORT.md)为准。

只交用户请求成果：部门/表演建议、离线方法包、修复/声剪计划或评估；不强制生成全部资产。完整空间交付继续按[空间规范](BLOCKING_COMPLETE.zh-CN.md)与[身份规范](CHARACTER_VISUAL_IDENTITY.zh-CN.md)，Excel/长镜分页/设计板继续按[交付指南](DELIVERY_GUIDE.zh-CN.md)。
