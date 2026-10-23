> 4.4执行增补：角色颜色、短编号和辅助标识来自项目级登记表，跨场不可按列表顺序重排。完整交付还需校验登记版本及同场身份冲突。详见docs/CHARACTER_VISUAL_IDENTITY.zh-CN.md与docs/BLOCKING_COMPLETE.zh-CN.md；下文旧几何样例不含这些新增必需输入，不能直接当完整4.4交付模板。

> 4.3执行增补：本页旧几何规格仍可参考，但完整交付必须有独立roster，漏场/镜/展开角色为错误而非警告。当前产物为场景总览＋逐镜entry/exit/movement SVG与PNG＋coverage。完整规则/设计板接入以docs/BLOCKING_COMPLETE.zh-CN.md为准，4.4不再生成旧场景聚合双图，旧文件仅供历史追溯。

# 每场景角色站位图、走位图与剧情连续性审核

本模块吸收用户提供的film-blocking-v1.0的空间规格与确定性示意图思路；不依赖安装该技能。默认面向本次输入的**全部场景、全部原镜**，不采用附件“只做一个地点、2–4镜”的默认范围。

## 交付与时机

新剧本在角色/场景档案之后先拟定空间方案，分镜及Director Contract完成后绑定原镜并出图；已有分镜直接复用已批准设定。每场景交付：

- `overview.svg/png`：本场首镜起始状态及场地总览；不把不同镜头位置叠成同一时刻。
- 每镜独立 `entry.svg/png`、`exit.svg/png`：首态/末态站位、朝向、画内/画外人物、地标和机位；不只画全场第一帧。
- 每镜独立 `movement.svg/png`：实际路径、方向、起终点、时间段与动作依据；不动的人注明原地，空镜注明无人。不得省略无位移场景的走位图。
- 场景覆盖索引、源绑定的 `blocking-spec.json`、程序校验报告、人工/Agent看图及剧情审核记录。

SVG是实际可打开的矢量示意图，不依赖生图API。当前完整图件从共享绘图定义同时绘制SVG与PNG，无需SVG转换器；任意外部SVG转换不属于这一路径。HTML索引本地离线显示，不加载CDN。

站位/走位图是空间设计文档，可以覆盖整场长时间动作，不受“执行故事板每板≤15秒”的排版时长约束；它不增加影片镜号、切点或时长。站位图和走位图相互配套，不能用一张电影剧照或一段提示词代替。

只处理用户指定片段时仍需覆盖该片段全部场景，并在交付说明明确“仅本片段，非全片覆盖”。只编译提示词/局部修图时读取现有图与审查，不重画无关场景。

## 一个剧情来源，独立的空间侧文件

继续以Director Contract的 `source_shots`、`shots`、`beats`、`continuity` 为剧情/时序事实源，schema3.0.0不变。空间侧文件只补几何，不复制另一套故事。`contract_sha256`用 `director_core.digest(读取后的合同JSON对象)`，不是随手填文件路径或原Excel哈希。

区分：`scene_id`是当前合同的剧情场景标识；`location_id`是物理地点。不同场次回到同一房间，可共享location，不复制一份偷偷变形的房间。若原合同错误地混用地点与场次ID，先标明对应关系并修正候选，不擅改已批准合同。

几何坐标是世界位置，不是摄影机画面左右。原点在bounds左下，+x向右、+y向上，朝向0°=+x、90°=+y。`schematic + relative`用于无测量资料的相对示意，必须写推断依据；只有真实尺寸依据才能用 `measured + m`。不能把未知房间“猜成12米”后宣称精确落地。

`cast.id`优先复用character_bible和合同subjects；群体可保留分组ID用于归属，但完整交付必须在独立roster中展开每个成员，并逐人登记视觉身份；不得用一枚标记代替多人或只写总人数。角色暂时出画仍保留其世界位置，`visibility=offscreen`，不能直接从characters删除。真实进入/离开场景需在剧情依据、空间边界与过渡审核中记录；必要时把门外暂存区纳入示意bounds。人物视线、持物、支撑脚等仍通过原合同continuity和看图检查，不假装平面点完整表达了表演。

## blocking-spec.json 结构（1.0）

完整可运行例子见 `examples/blocking-demo/blocking-spec.json` 及同目录 `director-contract.json`。

```json
{
  "schema_version": "1.0",
  "contract_sha256": "由合同JSON计算",
  "locations": [{
    "id": "cafe", "name": "咖啡店", "coordinate_mode": "schematic", "units": "relative",
    "basis": "门口在南、桌在中部；距离仅为调度示意",
    "bounds": {"x": 0, "y": 0, "w": 12, "h": 8},
    "landmarks": [{"id": "table", "label": "桌", "x": 4, "y": 4, "w": 2, "h": 1, "blocking": true}],
    "walls": [[[0,0],[12,0]]]
  }],
  "cast": [{"id": "A", "name": "甲", "color": "#2563eb"}],
  "scenes": [{
    "scene_id": "SC01", "location_id": "cafe", "cast_ids": ["A"],
    "shots": [{
      "shot_id": "S001", "source_shot_no": "1", "duration_sec": 4,
      "evidence": [{"field": "action", "quote": "甲走到桌旁"}],
      "characters": [{"id": "A",
        "entry": {"x": 6, "y": 1, "facing_deg": 90, "visibility": "in_frame"},
        "exit": {"x": 6, "y": 3, "facing_deg": 90, "visibility": "in_frame"}
      }],
      "trajectories": [{"who": "A", "beat_index": 0, "start_sec": 0, "end_sec": 4,
        "points": [[6,1],[6,3]], "reason": "按原镜甲走到桌旁"}],
      "cameras": [{"id": "CAM_A", "x": 9, "y": 2, "facing_deg": 160}],
      "transition": null
    }]
  }]
}
```

上例仅解释格式，不能直接把占位哈希用于执行。地标x/y是矩形中心，w/h为宽高；墙必须分段画出，门洞用墙段之间实际空隙表示，不在封闭墙上只贴“门”文字。未知机位允许 `cameras: []` 并列为待定，不编造已经批准的摄影参数。

每镜必须映射真实shot_id/source_shot_no/duration，evidence引用对应source_shots的action/notes/narrative_intent原文片段。每条路线用beat_index及镜内start/end时间关联真实动作节拍，原因具体说明剧情目的。角色在本镜起点=entry，全部路线连成一条时间链，终点=exit；没有位移时用空trajectories。不要把附件“本镜pose可能是起点也可能是终点”的歧义带入。

每个场景的cast_ids涵盖该场全体已登记角色，逐镜characters保留它们，包括画外。全场空镜允许cast_ids与characters均为空。非空场景中的空画面将世界中仍存在者标为offscreen，并在导演审核中解释。

连续同场前镜exit对齐本镜entry位置与朝向；机位变化导致visibility变化不等于人消失。真正时间跳跃或回场使用 `transition: {"kind":"time_jump"或"scene_return", "evidence":"具体源文及批准依据"}`，只能产生待人工审核的例外，不能填teleport绕过剧情。连续性容差是浮点计算容差，不是允许演员无故移动35厘米。

## 执行命令

所有路径相对实际项目；Skill目录只存能力文件。先运行原合同来源校验，再构建空间图：

```text
python <SKILL_ROOT>/scripts/director_pipeline.py validate <项目>/directing/director-contract.json --source <项目>/directing/source.json
python <SKILL_ROOT>/scripts/director_blocking.py <项目>/directing/blocking-spec.json --contract <项目>/directing/director-contract.json --roster <项目>/directing/roster.json --identity-registry <项目>/directing/identity-registry.json --out-dir <项目>/review/blocking
```

默认拒绝覆盖既有产物。上游修改后将旧输出标为失效，再用新版本目录或明确 `--overwrite` 重建；不得把新JSON与旧SVG混为一批。

工具校验全镜覆盖、场景/镜号/时长映射、原文引用、坐标有效性、角色引用、时间与路径链、相邻连续性。它不理解剧情：引用字句存在不代表路线服务叙事，也不证明源文本本身正确。碰撞自动检查至多为平面中心线近似；身体体积、动态碰撞、接触/攀爬/推拉家具必须看图及动作语义审核。

## 三层审核：必须实际完成，不自动打勾

1. **结构/覆盖**：运行命令，逐场核对完整剧本或导入快照的场景清单、镜号、人数和时长。合同仅含片段时不得报告全剧本覆盖。错误阻塞出图；警告全部列入待审。
2. **剧情相关性**：逐镜读取原文及前一镜/后两镜（因果链延伸到结果）。对照图解释站位如何支撑可见动作，走位为何在此时发生；核验对白关系、视线揭示、碰撞/救援通道、道具状态以及“未发生”的动作。无原文依据的空间推断单独标注候选，不能借路线加戏。
3. **实际图与连续性**：实际打开两类SVG/预览或转换后的图片，查看每一页；检查标签遮挡、首末态、箭头方向、机位与轴线、路径穿墙/穿家具/穿人、出入门、画外人物及前后镜状态。对同地点前后场次和跨场持物/服装另行检查。不能只读JSON后声称已看图，也不能用浏览器打开成功代替内容审核。

在项目保存 `directing/blocking-review.json`，至少含合同哈希、spec哈希、每场景两类文件路径和当前文件哈希、`structure`、`story_relevance`、`continuity`、`visual_diagram_review`四项状态，以及逐场逐镜证据、审阅者/方式、问题、待确认项和修复影响范围。状态用pending/passed/failed/needs_manual_review；实际问题未解决不写passed。脚本输出始终为needs_manual_review，Agent依据实际检查另写审核记录。

交付前重新计算哈希：合同/spec/任何SVG变化均使相关审核失效；不能沿用旧passed。缺少可看图工具时图可交付，但视觉审核标needs_manual_review并清楚说明，不声称该场完成全部审核。

审核通过的世界关系回写原合同continuity、opening/ending、beats及constraints；必要时先获得锁定项变更授权。随后重算spec合同哈希、重出图并复查，避免合同/图/视频prompt三份叙事互相矛盾。把图作为空间参考给媒体工具时真正提交对应图；它不替代角色身份图或视频首帧，不默认塞进不支持该参考职责的素材槽。

## 局部修复

角色位置/路线改变：检查该镜、上一末态、下一首态及关联因果镜。地点布局改变：同location_id全部场次重出图，重新审核可通行区域。保留修订前版本，在project-state标记受影响图、提示词和执行板失效；不重画无关地点。
