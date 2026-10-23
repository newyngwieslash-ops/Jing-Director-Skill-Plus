# Director Shot Contract 与字段职责

可执行结构以 `schemas/director-contract.schema.json` 为准，完整样例见 `examples/hall-shot-09/director-contract.json`。本文件解释语义，不另造第二套同名结构。

## 三层事实

`source_shots`是导入的源事实快照，保存原镜号、原行、原文与原时长。`shots`是导演解释后的执行层；`generation/*/prompt.txt`是模型可读编译结果。修改编译文字应先在执行层修正，再重编译，避免prompt与审阅板描述不同的电影。

`project.source_sha256`对应原文件哈希。运行 `validate --source source.json`同时比较源快照，防止为通过校验擅改源行。哈希只是内容一致性，不是来源真实性或用户批准的证明。

| 字段 | 职责 | 提交视频模型时 |
|---|---|---|
| source_shot_no / source_span_sec | 追溯与时长守恒 | 不作为剧情文本上传 |
| director | 观看任务和摄影理由 | 转成可见行动，不把抽象分析原封不动塞prompt |
| camera | 人审摄影选择 | 由Agent落实到opening、beats.camera、ending中的可观察描述 |
| continuity | 世界/轴线/道具状态 | 只编译本镜必须守住的具体视觉约束 |
| opening / ending | 首尾可见状态 | 模型时间轴锚点 |
| beats | 非等分动作/摄影/声音时间段 | 同一镜内分阶段展开，不误变cut |
| dialogue | 原文、说话人、时间、画内外 | 保持原语言和确切文字，H3专门格式化 |
| keyframes | 确定时刻的可见画面 | 生成干净图片；按模式选首尾或参考 |
| assets / reference_asset_ids | 真实参考与职责 | 编译上传计划，不自动上传 |
| review | 独立审核状态 | 不作为模型能够理解的“质量保证” |

注意：离线编译器不理解导演语义。**Agent必须先把camera对象里的决定同步到视觉时间轴字段**；程序不会把“85mm”自动改成一段优美电影语言。模板保留中英文字段；Seedance使用zh，H3使用en但dialogue.text不翻译。H3缺英文时编译失败，避免自动编造译文。

## 时间、镜号与拆分

`source_span_sec=[0,10]`表示来源镜内0–10秒，而非整集时间码。原Excel的绝对码留在raw_cells。源镜9可以命名S009；不要把内部排序ID误当原镜号。

`preserve_shots`要求一行源镜对应一个摄影镜头。批准拆分后改为`approved_recut`，例如原20秒可拆S001a[0,9]与S001b[9,20]；每段beats与keyframes的时间从自己的0秒起算。拆分需真实批准且同一源镜分段连续、总时长守恒。来源镜合并成一个新长镜暂不支持，需要先修订源镜表。

人审板按原序、同场景、累计≤15秒分组。每个关键帧标的是瞬间，不是额外占据的时长。生成任务可使用相邻若干镜，但要保留真实切点；不能把多镜合并任务伪称“单镜”。

## 最低导演字段

四项director决策非空；camera的首尾景别、相机高度/角度、运动、视差证据、焦点与构图非空。lens_mm/fov_deg可空，明确未知比无依据数值更好。起止状态、beats、音景和关键帧有中英结构；plan阶段只要求中文，H3编译再要求英文。

不要给尚未设计的输入默认“固定镜头”“全景”骗过schema。`init`输出`draft`和UNRESOLVED，故意不能直接编译；Codex负责导演设计，不是让Python猜审美。

## 审核状态

`shots.status`：draft → planned → generated_unverified → reviewed。
`review.director`是拍法批准；`keyframes.visual_review`是真实图像审查；`review.user`是用户认可；`review.video`是真实动态片审查。流程可回退，只要某个上游事实变化，就将受影响下游标为待复核。

production校验核对本地文件、记录的实际生图输入回执字段、图像审查证据和批准状态。它不能认证回执是否来自供应商，不能看图核脸，不能证明物理运动、语义等价或商业权利。不要把这些字段当成可以自动填`passed`的表格任务。
