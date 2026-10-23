# 逐场景逐镜空间图虚构示例

内容保真升级说明：本例继续保留虚构、未批准状态，不自动填入 `dialogue_baseline` 审核人或生成回执。用于非草稿视频编译或生产检查前，必须由真实审阅者独立核对源快照、逐镜明确对白基线（无对白为经审核的 `lines: []`），并绑定实际输入、输出文件的 SHA-256 与视觉审核。迁移字段与流程见 `../hall-shot-09/README.md`。本例现有预览不是新生产门禁通过证明。

用于测试与教学，不是用户项目的已批准拍摄方案。

- SC01：S001林晓桌旁、周衡门内均静止；S002林晓原地，周衡从门内绕桌东侧接近并停住。
- SC02：S003店外无人空镜，验证空场也输出总览及逐镜首末态、走位图。
- 坐标为相对示意，非实测；来源在source-table.json，导入快照source.json，导演合同与blocking-spec按哈希绑定。

运行 `python <技能根>/scripts/director_blocking.py <本目录>/blocking-spec.json --contract <本目录>/director-contract.json --roster <本目录>/roster.json --identity-registry <本目录>/identity-registry.json --out-dir <项目输出>`。

输出的静态站位/走位图不等于真人镜头、图像模型结果或动态视频验证。审阅协议详见references/scene-blocking.md。

历史参考：可打开 `preview/index.html` 查看4.1旧版四图，不代表4.4固定标识结果。`preview/blocking-review.json`记录本次Agent对虚构示例的实看图与剧情审核；程序manifest仍保持needs_manual_review，二者职责不同。

当前完整空间图入口：blocking-complete/index.html；空间设计板入口：design-spatial/index.html。原preview目录是4.1历史双图演示，不是本次4.4完整交付入口。


## 4.4 项目固定角色视觉标识

本示例的 `identity-registry.json` 是当前项目唯一角色视觉标识表，版本为 revision 1。
`character_id` 绑定固定 `short_code`、颜色、标记形状及走位线型；不会按单镜人物顺序重新分配。
两个示例是两个独立项目，各自的 C001 等编号不表示跨项目的同一个人物。

- `blocking-spec.json` 的 `identity_binding` 使用规范化注册表摘要；`cast.color` 必须与注册表一致。
- `design-spatial-spec.json` 除了绑定图件 manifest，还指向当前项目注册表及其原始文件摘要；仅替换为一个内部自洽的旧图件包不能冒充当前配色版本。
- 空间图使用固定编号和色形标识；首末位 E/X、画外 OFF、朝向及走位方向是独立状态，不会改变身份色。
- 颜色是导演示意图身份标签，不是服装、阵营、心情或来源剧本明确的外观事实。
- 形状和线型提供额外辨识；静止人物无走位线时仍由固定编号、颜色、形状区分。
- 当前只代表离线示意，未获得艺术审核批准，也不宣称通过色觉无障碍认证。

重新生成时必须传入 `--identity-registry identity-registry.json`，并在设计板绑定中更新重新生成图件 manifest 的摘要。
当前完整入口为 `blocking-complete/index.html`、`design-spatial/index.html`；其他旧版规划或预览文件仅作历史参考。
