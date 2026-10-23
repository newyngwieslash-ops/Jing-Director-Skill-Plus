> 统一版保留资料：仅按当前任务读取。已批准源表、当前 SKILL.md 和 Director Contract 规则优先；历史格式/模型能力描述不代替实际供应商核验。固定15秒/8格、强制加镜及把整页板默认提交视频的旧口径不适用。

# 角色提取与全局一致性规范

本规范用于导演工作流第四步“提取角色以保持全局一致性”。目标是在分镜、生图、执行故事板、视频生成之前，先建立统一角色档案，并为主要/常驻角色生成三视图参考图，避免同一角色在不同镜头中脸、服装、年龄、气质跳变。

---

## 1. 核心链路

1. **提取**：从剧本全文、场景标题、动作描写、对白署名、声音提示中提取全部角色。
2. **建档**：输出 `character_bible.json`，把角色身份、视觉特征、对白风格和连续性规则固定下来。
3. **建锚**：为主角、常驻配角、跨场景复现角色生成三视图基准图提示词。
4. **强参考资产**：为主角、常驻配角、跨场景复现角色补齐三视图、脸部近景、当前场景服装图、身份锚点和禁止漂移项。
5. **生图**：提取角色后先生成每个主要/常驻角色的参考图，并把图片路径或生成结果编号写回角色档案。
6. **注入**：后续分镜表、视频提示词、执行故事板图片、关键帧图片都必须引用 `character_bible.json`。
7. **实际提交**：三视图/脸部近景/服装图生成图片或视频时必须作为实际参考图输入一并提交；只在 prompt 里写“参考某角色”不算完成一致性注入。

> 工程判断：关联提交角色图和场景图是必要条件，不是充分条件。如果仍然一次性让 GPT image 2 生成整张 8 行执行故事板，角色一致性依然会漂。生产级执行故事板必须改为“参考图强绑定 + 单格生成 + 代码合成 + 视觉验证”。

---

## 2. 提取范围

必须提取：

- 有对白或动作的具名角色。
- 没有名字但反复出现或承担叙事功能的角色，如“酒保”“保安”“护士”“COS英雄男”。
- 同一人不同称谓、别名、英文名、身份伪装、COS身份。
- 会进入画面的群像模板，如“路人”“警员”“游客”，但群像可以用模板化角色，不必逐个建独立角色。
- 只被提及但后续可能需要画面呈现的角色。

不应提取：

- 纯抽象概念、道具、地点。
- 一次性背景人群中的不可区分个体，除非用户要求固定。

---

## 3. 去重与名称对齐

名称规范化规则：

- 去除括号及括号内说明，例如 `贞德（COS）` 归一为 `贞德`。
- 去除多余空格、全角/半角差异、称谓后缀。
- 合并同一角色的中文名、英文名、外号、职务称呼。
- 为每个角色生成稳定 `id`，推荐小写蛇形命名，例如 `gao_xing`、`cos_hero_man`。

如果无法确定两个名字是否同一人，先保留为两个角色，并在 `continuity_rules.pending_identity_questions` 中记录疑点，不要擅自合并。

---

## 4. character_bible.json 标准结构

```json
{
  "project": {
    "title": "项目名",
    "era_background": "全局时代/世界观",
    "visual_continuity_rule": "所有图像和视频生成必须引用本文件中的角色 id、视觉特征和参考图"
  },
  "global_character_rules": [
    "不允许临时改变角色年龄、脸型、体型、发型、核心服装轮廓",
    "如分镜中出现未登记角色，必须先补录 character_bible.json 再继续",
    "主角和常驻配角必须使用三视图/头像参考图"
  ],
  "characters": [
    {
      "id": "stable_character_id",
      "name": "角色姓名",
      "aliases": ["别名", "称谓", "英文名"],
      "importance": "lead | supporting | recurring | minor | crowd_template",
      "first_appearance": "EP1 Scene 1",
      "appears_in": ["EP1 Scene 1", "EP2 Scene 3"],
      "era_background": "时代背景或所属世界观",
      "occupation": "职业或社会地位",
      "role_description": "身份、背景、性格与叙事功能",
      "visual_traits": "详细视觉特征：年龄、发色、发型、脸型、五官、体型、服装、道具、气质",
      "key_visual_traits": [
        "不可改变的核心视觉锚点1",
        "不可改变的核心视觉锚点2",
        "不可改变的核心视觉锚点3"
      ],
      "wardrobe": {
        "default": "默认服装",
        "scene_variants": {
          "EP1 Scene 2": "该场景服装变化"
        }
      },
      "dialogue_traits": "说话风格、口癖、语速、口音、情绪表达方式",
      "performance_traits": "肢体动作、表情习惯、站姿、反应节奏",
      "continuity_rules": [
        "后续所有镜头必须保持的规则",
        "允许变化与不允许变化的边界"
      ],
      "negative_prompts": [
        "不要把角色画成另一种年龄",
        "不要改变发型或核心服装轮廓"
      ],
      "triple_view_prompt": "用于生成角色三视图基准图的提示词",
      "triple_view_prompt_json": {
        "type": "character three-view reference sheet",
        "layout": "front view, 90-degree side view, back view"
      },
      "reference_assets": {
        "avatar_url": "",
        "triple_view_url": "",
        "triple_view_image_path": "",
        "triple_view_image_id": "",
        "identity_sheet_path": "",
        "face_closeup_path": "",
        "wardrobe_sheet_paths": {
          "default": "",
          "scene_id": ""
        },
        "approved_panel_samples": [],
        "generation_status": "pending | generated | confirmed",
        "local_reference_paths": []
      },
      "identity_anchors": {
        "face_shape": "脸型",
        "hair": "发型/发色/发际线",
        "body": "身高、体型、肩颈比例",
        "signature": ["最不可变的3-5个辨识点"]
      },
      "identity_forbidden_drift": [
        "do not change face shape",
        "do not change age band",
        "do not change hairstyle",
        "do not change wardrobe silhouette",
        "do not replace this actor with a generic character"
      ],
      "actual_reference_input_policy": {
        "execution_storyboard_panels": "must submit face_closeup_path, active wardrobe_sheet_path, and relevant triple_view_image_path as actual image inputs",
        "prompt_only_allowed": false,
        "missing_reference_status": "blocked_missing_reference_image"
      }
    }
  ],
  "crowd_templates": [
    {
      "id": "crowd_template_id",
      "name": "群像模板名",
      "visual_traits": "群像整体视觉规则",
      "usage": "适用场景"
    }
  ]
}
```

---

## 5. 必填字段判定

每个非群像模板角色必须至少具备：

- `id`
- `name`
- `aliases`
- `era_background`
- `occupation`
- `role_description`
- `visual_traits`
- `key_visual_traits`，3-5条最稳定的视觉锚点
- `dialogue_traits`
- `performance_traits`
- `continuity_rules`
- `negative_prompts`
- `reference_assets`

如果原文信息不足，可以用“根据当前剧本暂定”标记，但不能留空。暂定项必须在 `continuity_rules` 中标注后续需要复核。

执行故事板生产级生成还必须具备：

- `reference_assets.triple_view_image_path`
- `reference_assets.face_closeup_path`
- 当前场景可用的 `reference_assets.wardrobe_sheet_paths[scene_id]` 或 `reference_assets.wardrobe_sheet_paths.default`
- `identity_anchors`
- `identity_forbidden_drift`
- `actual_reference_input_policy.prompt_only_allowed = false`

缺少上述任一项时，可以继续生成提示词草案，但不得把执行故事板状态标记为 `verified_identity_scene_layout`。

---

## 6. 三视图参考图生成

主角、常驻配角、跨场景复现角色在视觉生产前须生成三视图参考图。至少输出自然语言 `triple_view_prompt` 和结构化 `triple_view_prompt_json`。有工具且已授权时执行生图；没有工具则交付提示词并登记缺图，可继续文本分镜与Excel草稿，不得声称视觉一致性已确认。

自然语言模板：

```text
TRIPLE-VIEW CHARACTER SHEET for [角色名 / id].
Create the same real human actor in three views: front view, 90-degree side view, and back view.
Keep the exact same face, age, body build, hairstyle, costume, makeup, props, and color palette across all views.
Era/background: [era_background].
Occupation/social role: [occupation].
Core visual anchors: [key_visual_traits].
Detailed visual traits: [visual_traits].
Performance attitude: [performance_traits].
Cinematic live-action realism, no 3D, no CGI, no game character look, no anime.
Clean neutral background, 16:9 wide character reference sheet.
Include the character name/id in the top-left corner.
Negative: [negative_prompts].
```

结构化 JSON 模板：

```json
{
  "type": "character three-view reference sheet",
  "setting": "clean neutral studio background, soft even lighting, reference image for later storyboard and video generation",
  "character": {
    "id": "[stable_character_id]",
    "name": "[角色名]",
    "age": "[年龄段]",
    "body": "[体型、身高、比例]",
    "face": "[脸型、五官、辨识特征]",
    "hair": "[发型、发色]",
    "outfit": "[服装、材质、年代感]",
    "props": "[关键道具]",
    "palette": "[角色主色与辅助色]",
    "performance_attitude": "[表演气质]"
  },
  "layout": {
    "arrangement": "one image containing three full-body views",
    "views": [
      {"position": "left", "description": "front view, neutral pose"},
      {"position": "center", "description": "90-degree side view, neutral pose"},
      {"position": "right", "description": "back view, neutral pose"}
    ],
    "consistency": "same face, same age, same body build, same hairstyle, same outfit, same props, same color palette across all views"
  },
  "style": {
    "visual_style": "[电影真人质感或项目既定风格]",
    "director_tone": "[第一步确认的导演定调]",
    "camera": "orthographic-like neutral character reference, no dramatic angle"
  },
  "constraints": [
    "no extra characters",
    "no pose variation",
    "no facial redesign between views",
    "no outfit change between views",
    "plain background",
    "reference sheet only",
    "include character name and id in the top-left corner"
  ],
  "negative": "[negative_prompts]"
}
```

用户提供的“人物角色设定图”JSON 示例可作为结构化提示词写法参考，但本步骤的目标是三视图角色设定图，不是两排拍立得写真合集。必须把示例中的 `layout.photos` 改写为正面、侧面、背面的 `layout.views`。

生成后必须写回：

- `reference_assets.triple_view_image_path` 或 `reference_assets.triple_view_image_id`
- `reference_assets.generation_status`
- `reference_assets.local_reference_paths`
- 需要用户复核的外观假设

---

## 7. 后续步骤注入规则

### 分镜拆解

- 分镜中的“人物”必须来自 `character_bible.json`。
- 如出现新人物，先补录角色档案，再继续拆镜。
- 不得在分镜表里新增与角色档案冲突的年龄、服装、脸型、体型描述。

### 视频提示词

每条视频提示词的【人物】字段必须包含：

```text
角色名@（引用 character_bible id；核心视觉锚点；对白风格；画面无字幕/或按需说明）
```

如果镜头中有多人，逐一列出，不能只写“众人”。

### GPT image 2 分镜图 / 执行故事板图

每次生图必须提交：

- 当前画面提示词。
- `character_bible.json` 中当前镜头相关角色片段。
- `art_style_bible.json` 或已确认美术风格。
- 当前角色的 `reference_assets.triple_view_image_path` 指向的实际三视图图片。执行故事板图片生成时必须逐一读取这些图片并作为 GPT image 2 参考图提交；不得只写文字说明，也不得用未登记在该字段中的图片替代。

提示词必须明确：

```text
Use the provided character_bible.json as strict identity reference.
Match each visible character by stable id.
Preserve face, age, body build, hairstyle, costume silhouette, color palette, and performance traits.
Use the actual image files from reference_assets.triple_view_image_path as mandatory visual anchors.
Generate and obey wardrobe_lock for every visible character: use wardrobe.scene_variants[current scene] if present, otherwise wardrobe.default. Copy the outfit from the attached triple-view reference image unless the scene-specific wardrobe variant explicitly changes it.
For execution storyboard images, use layout_standard: execution_storyboard_with_bottom_character_reference_strip.
For execution storyboard images, write bottom_character_reference_strip into the board manifest and prompt.
For execution storyboard images, include a bottom character reference strip titled “角色参考（服装造型一致）” inside the generated image. The strip must show each visible recurring character's actual triple-view reference thumbnails from reference_assets.triple_view_image_path and a wardrobe_lock summary.
If the generated image lacks the bottom strip, set visual_consistency_status to failed_missing_bottom_character_reference_strip and do not mark confirmed.
If the main panels drift from the bottom references in face, age, body build, hairstyle, outfit silhouette, or color palette, set visual_consistency_status to failed_visual_consistency and do not mark confirmed.
Do not invent unrelated characters or alter established character identities.
```

### 视频生成

用于 Seedance、Sora 或其他图生视频模型时，优先使用已经通过角色一致性校验的关键帧/执行故事板图，再提交对应的视频提示词。不要直接从没有角色锚点的纯文本生成长视频。

---

## 8. 自检问题

- 是否有任何对白署名没有进入 `characters`？
- 是否有任何画面中出现的人没有 `id`？
- 是否把“同一人不同称谓”错误拆成多个角色？
- 是否把“不同角色同称谓”错误合并？
- 是否每个主要角色都有足够稳定的视觉锚点？
- 是否已为主要/常驻角色生成三视图参考图，而不是只留下提示词？
- `reference_assets.triple_view_image_path` 是否已写入实际图片路径，且后续 GPT image 2 生图时会读取该字段对应图片？
- 三视图是否固定正面、90度侧面、背面，且三个视图是同一角色、同一服装妆发、同一体型比例？
- 后续执行故事板是否为每个 visible character 生成 `wardrobe_lock`，并把 `wardrobe.default` / `wardrobe.scene_variants[scene]` 注入提示词？
- 后续执行故事板是否记录 `layout_standard` 和 `bottom_character_reference_strip`？
- 后续执行故事板是否在生成图底部展示“角色参考（服装造型一致）”，而不是只在 prompt 中写参考三视图？
- 若缺少底部参考区或出现视觉漂移，是否标记 `failed_missing_bottom_character_reference_strip` 或 `failed_visual_consistency`，而不是 `confirmed`？
- 后续提示词是否明确要求加载角色 JSON，而不是只写“保持一致”？
