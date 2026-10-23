# 4.5 DirectorSKILL 选择性吸收说明

本次不是合并两个Skill：JingStudio保真、校验和交付仍是主干；上游只贡献局部方法。用户授权基于六类研究结论直接优化现有项目。未升级源Contract版本、未安装到任何客户端、未新增真实供应商提交或后期执行器。

## 范围与实现

| 研究增量 | 本包落点 | 不能据此声称 |
|---|---|---|
| 部门导演参数卡 | department-director-book.md；六部门规则旁挂 | 替换原六维定调或完整移植20风格 |
| 可观察表演 | observable-performance.md；逐镜表演记录 | 文本通过即真人感提升 |
| 故障/修复账本 | failure-repair-ledger.md；F1–F19/两个计数 | 自动删镜、拆镜或无限试错 |
| 能力路由 | capability-prompt-routing.md；S1–S4/unknown | API接通、供应商当前能力已测试 |
| 声音/剪辑计划 | sound-edit-planning.md；cue/计划映射 | 混音/NLE/实测媒体执行完成 |
| 行为评估 | evals/ 与离线评估工具 | 已有真实模型rollout或视频效果证据 |

全部方法均通过 `references/director-method-layer.md` 渐进加载；旁挂schema及工具入口见[METHOD_LAYER_QUICKSTART.zh-CN.md](METHOD_LAYER_QUICKSTART.zh-CN.md)。文本工作单补足当前schema之外的制作字段，不伪装成机器已执行。

## 保留而非重做

来源及对白保真、独立typed roster、项目级固定角色标识、场景总览、逐镜首末/走位SVG和PNG、时序关键帧、Excel往返、无切点长镜分页、设计板和审核证据绑定沿用4.4实现。新方法的合同角色引用不能取代群体逐人展开；艺术调色不能改变角色图身份色。

## 固定来源与采用方式

上游仓库 https://github.com/wuwangzhang1216/DirectorSKILL ，固定提交 `c65ae0d14457053efb1e354c7e7f7e120d97fad1`。研究时获取55个文本文件并校核Git blob；该事实是研究覆盖范围，不是本包测试数量。仓库2.1.0中的20风格模块没有整体搬入，仅提炼少量机制；上游57行为用例为规格，不当作57项已执行模型评测。

| 上游文件（均相对固定提交） | 采用/改写至 |
|---|---|
| references/director_styles/README.md 及机制相关风格结构 | 部门卡结构、局部作用域、反例；非全量预设 |
| references/blocking-and-staging.md、prompt-lexicon.md | 表演任务/注意/触发/接触/终态方法，新增来源分类与锁定限制 |
| references/failure-modes.md | F1–F19症状类别、低损耗阶梯和跨设计预算；按现有门禁改写 |
| references/ai-video-tool-adapters.md | S1–S4与V2V控制面；不沿用未经重核的品牌能力结论 |
| references/sound-and-dialogue.md、editing-and-assembly.md | 五声部/SPACE、剪辑交接；加强对白和时长保真 |
| evals/run.md 与用例结构 | 隔离生成/评分、逐断言证据、hard-fail；本地独立用例/实现 |

固定源码链接前缀：`https://github.com/wuwangzhang1216/DirectorSKILL/blob/c65ae0d14457053efb1e354c7e7f7e120d97fad1/`。这是方法适配而非上游官方发行；没有执行上游CI或安装脚本，没有复制完整上游Skill。

MIT归属与许可全文见[第三方许可证](../third_party/DirectorSKILL/LICENSE)，copyright2026 wangzhang-wu。该许可只适用于相应上游材料，不覆盖整个混合来源项目；其他原作者权利见[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 验收边界

结构校验与离线回归防止已定义退化，不证明未知剧情完整性、专业动作准确、供应商兼容或影片艺术品质。真实项目原始素材、独立来源复核、模型回执与看片证据未提供时保持未验证。4.4测试日志已作为历史保留；4.5实际结果由当前TEST_REPORT记录，不挪用旧239项数字当新测试。
