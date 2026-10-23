# Seedance 2 专用视频生产故事板规范

本文件定义从已确认分镜 Excel 或第七步执行故事板 manifest 生成《Seedance 2 专用视频生产故事板》的规则。该步骤不是普通单镜头视频提示词，也不是 GPT image 2 故事板图片提示词；它把连续剧情分镜加工为可交给 Seedance 2 的 15 秒内多参考视频生产单元。

## 一、启用条件

当用户提出以下需求时启用本步骤：

- Seedance 2 / seedance2 专用视频提示词
- 将分镜 Excel 加工成 Seedance 2 视频生产故事板
- 多参生视频提示词、多参考图生视频、按 `@角色` / `@image` / `@scene` 引用
- 将连续分镜整合为 不超过15秒的视频生成单元
- 需要 `0-x秒`、`x-y秒` 的分秒级镜头控制

执行本步骤前必须具备：

- 已确认的分镜 Excel，标准九列或含 `视频提示词` 列均可。
- `character_bible.json`，且所有可见主要/常驻角色均有稳定 `id`。
- 主要/常驻角色的 `reference_assets.triple_view_image_path`；缺失时必须标记阻塞，不得声称角色一致性已确认。
- 如已有第七步 GPT image 2 执行故事板图，应在本步骤中以 `@storyboard_<boardId>` 作为 Seedance 2 参考别名。
- 生产级视频还应引用第七步逐格 panel 图、角色脸部近景、当前场景服装图和 scene plate；未通过 `verified_identity_scene_layout` 的执行故事板不得标记为投产就绪。

## 二、输入字段兼容

从分镜 Excel 中按语义识别以下字段：

| 标准字段 | 可接受列名 |
|---|---|
| 镜号 | 镜号、镜头号、分镜、编号 |
| 时长 | 时长、持续时间、秒数 |
| 摄影角度 | 摄影角度、机位、角度 |
| 景别 | 景别、镜别 |
| 画面内容 | 画面内容、画面、视觉内容 |
| 场景 | 场景、场次、地点 |
| 声音 | 声音、台词/声音、音效/音乐 |
| 运镜 | 机位/运动、运镜、镜头移动、备注 |
| 叙事目的 | 叙事目的、目的 |
| 视频提示词 | 视频提示词、AI视频提示词、文生视频提示词 |

## 三、分组规则

- 严格从分镜 1 到分镜 X 顺序处理。
- 每个源分镜必须且只能进入一个 Seedance 2 视频故事板。
- 每组只允许包含连续分镜，不得重排、跳号或把非连续分镜放入同一组。
- 单组硬上限为 15 秒。
- 每板时长大于0且不大于15秒，不设最低秒数；短板及单镜头成板均有效，优先保持场景和动作连续性，不强制凑满15秒。
- 单个源分镜超过 15 秒时不得直接生成 Seedance 2 故事板，必须先拆分源分镜。

## 四、每个故事板必须输出的字段

每个 Seedance 2 视频故事板 manifest 至少包含：

- `boardId`：如 `EB-001`。
- `shotRange`：源分镜范围。
- `sourceShotNos`：本板包含的源分镜号，按顺序排列。
- `totalDurationSec`：总时长，不得超过 15。
- `characters`：参与角色，含稳定 `id`、中文名、`@` 角色别名、视觉锚点和服装锁。
- `sceneRefs`：场景引用，允许文本场景引用。
- `imageRefs`：可附加图像引用，必须区分角色三视图、场景图、故事板图。
- `storyboardImageRef`：第七步 GPT image 2 执行故事板图引用；未生成时仍保留 `@storyboard_<boardId>` 并标记 `pending_image_generation`。
- `shotDescription`：按源分镜顺序合并的镜头描述。
- `dialogueSound`：按源分镜顺序合并的对白和声音。
- `timeSegments`：分秒段落，覆盖 0 到本板总时长。
- `gptImage2Prompt`：本板对应的 GPT image 2 故事板图提示词。
- `seedance2MultiRefVideoPrompt`：Seedance 2 多参生视频提示词。

## 五、引用符号规则

Seedance 2 提示词必须使用稳定 `@` 引用，而不是只写自然语言描述。

| 类型 | 格式 | 示例 |
|---|---|---|
| 角色 | `@character_id` 或 `@角色名` | `@su_fei`、`@苏菲` |
| 角色三视图 | `@image_<character_id>_triple_view` | `@image_su_fei_triple_view` |
| 场景 | `@scene_<slug>` | `@scene_冷宫院落` |
| 故事板图 | `@storyboard_<boardId>` | `@storyboard_EB-001` |
| 角色脸部近景 | `@image_<character_id>_face` | `@image_zhao_wuxu_face` |
| 场景服装图 | `@image_<character_id>_wardrobe_<scene_id>` | `@image_zhao_wuxu_wardrobe_jinyang_flood` |
| 场景图 | `@scene_<scene_id>_plate` | `@scene_jinyang_flood_plate` |
| 逐格画面帧 | `@panel_<boardId>_rowXX` | `@panel_EB-040_row01` |

manifest 必须记录 alias 到路径或来源的映射：

- 可附加图片引用：记录实际路径或资产 id。
- 文本场景引用：记录 `source`，并标记 `attachable: false`。
- 未生成的故事板图：记录 alias，状态为 `pending_image_generation`。
- 未验证的故事板图：记录 alias，状态为 `generated_unverified`，并设置 `video_generation_readiness: "blocked_unverified_storyboard_consistency"`。
- 已验证的执行故事板：只有 `visual_consistency_status: "verified_identity_scene_layout"` 时，才能设置 `video_generation_readiness: "ready"`。

## 六、Seedance 2 多参生视频提示词模板

每个故事板生成一条完整提示词。由于 Seedance 2 投产输入存在文本长度限制，本字段必须控制在 **2000 个 Unicode 字符以内**；详细角色设定、服装锁、缺失引用警告等长信息应保留在 JSON manifest 的结构化字段中，不得全部塞进投产提示词。

推荐结构：

```text
15-second Seedance 2 multi-reference cinematic video storyboard for 《项目名》, board EB-001.
Duration: 15 seconds, 16:9 horizontal cinematic framing, up to 1080p production intent.
Style: [项目影调、真实/动画/古装/悬疑等风格]; follow the source execution storyboard, no invented plot, keep scene continuity and shot order.
Primary scenes: @scene_xxx=...
Character references: @角色id (@角色名, 中文名) using @image_角色id_triple_view.
Image references to attach: @image_角色id_triple_view, @storyboard_EB-001.
sourceShotNos: 1,2,3.
Continuity lock: characters maintain consistent faces, age, body build, hairstyle, clothing silhouette, props, and voice identity; no deformation, drift, artifacts, or unregistered characters.
Wardrobe and identity lock: @角色id: [服装锁、视觉锚点、禁止漂移项].
Lip synchronization: if dialogue exists, mouth movement is subtle, natural, low-energy, and precisely synchronized; if no dialogue, keep mouth closed or naturally breathing.
Overall sound effects: preserve listed dialogue, environmental sound, Foley, music cues, short pauses, and emotional rhythm from each source shot.

0-4 seconds: sourceShotNos: 1. Use @scene_xxx and preserve source story order. Characters in motion: @角色id. Visual action: ... Camera movement: ... Performance detail: ... Dialogue: ... Sound: ...
4-9 seconds: sourceShotNos: 2. ...
9-15 seconds: sourceShotNos: 3. ...

Negative constraints: no text overlay, no subtitles unless explicitly requested by source shot, no watermark, no platform logo, no random signature, no unrelated characters, no extra plot.
```

写作要求：

- 全局段先交代时长、画幅、风格、场景、角色引用、图片引用、连续性和负面限制。
- 分秒段必须从 0 开始，单调递增，最后一个结束时间等于本板总时长。
- 每个分秒段必须写明 `sourceShotNos`、可见动作、运镜、表演细节、对白或无对白、声音。
- 对白必须按源分镜顺序保留；有对白时加入自然口型同步要求，无对白时明确无对白或自然呼吸。
- 只转写源分镜可见/可听信息，不新增剧情事实。
- `seedance2MultiRefVideoPrompt` 不得超过 2000 个 Unicode 字符；如超过，应优先压缩角色长设定、重复负面词、服装长描述和音效长说明，而不是删除 `@` 引用、分秒段或源分镜号。

## 七、校验规则

生成后必须校验：

- 源分镜是否全覆盖且只出现一次。
- 每组总时长是否不超过 15 秒。
- 是否保持源分镜时长，未为凑满15秒而填充或拉长。
- 所有 time segment 是否连续覆盖 0 到总时长。
- 每个 segment 的 `sourceShotNos` 是否与本板 `sourceShotNos` 对齐。
- 每个声明的角色 alias、图片 alias、场景 alias、故事板 alias 是否出现在 `seedance2MultiRefVideoPrompt`。
- `seedance2MultiRefVideoPrompt` 是否不超过 2000 个 Unicode 字符。
- 可见角色是否来自 `character_bible.json`。
- 每个可见主要/常驻角色是否有三视图引用；缺失时状态为 `blocked_missing_character_reference` 或等价阻塞状态。
- 提示词中不得声称缺失引用的角色一致性已确认。
- 负面限制是否包含无水印、无平台 logo、无无关署名、无未注册人物、无新增剧情。

## 八、输出格式

默认输出：

- JSON manifest：机器可读，记录所有故事板、引用映射、分秒段和验证警告。
- Markdown prompt list：人工可读，逐板列出 reference aliases、GPT image 2 提示词和 Seedance 2 多参生视频提示词。

可选输出：

- Excel 生产清单：包含 `boardId`、`shotRange`、`totalDurationSec`、`characters`、`sceneRefs`、`imageRefs`、`shotDescription`、`gptImage2Prompt`、`seedance2MultiRefVideoPrompt` 等列。
