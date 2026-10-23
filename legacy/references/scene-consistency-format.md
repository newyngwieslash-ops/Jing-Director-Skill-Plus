# 场景一致性资产规范

本规范用于导演工作流第四点五步“场景一致性资产”。目标是在执行故事板、关键帧和 Seedance 2 视频生产前，先锁定反复出现或视觉复杂场景的空间、光线、色彩、道具和气候状态。

## 1. 何时必须建立 scene_bible

- 同一地点会跨多个执行故事板反复出现。
- 场景空间关系会影响动作、调度或叙事。
- 场景有明确光线、天气、道具、时代质感要求。
- 用户要求长篇视频角色及场景一致性。

## 2. scene_bible.json 标准结构

```json
{
  "project": "项目名",
  "scenes": [
    {
      "scene_id": "scene_jinyang_flood",
      "name": "晋阳围城洪水",
      "scene_aliases": ["晋阳", "悬釜", "洪水城墙"],
      "era_background": "春秋末年晋阳城",
      "geography_layout": "城墙、屋顶、树杈、浑水、吊锅位置关系",
      "lighting_lock": "冷灰蓝潮湿天光，烟压水气",
      "palette_lock": ["cold gray blue", "mud brown", "wet black smoke"],
      "prop_locks": ["吊锅", "断木", "城墙夯土", "浑水"],
      "weather_time_lock": "围城洪水期，潮湿寒冷，白日灰光",
      "negative_prompts": ["modern buildings", "clean streets", "fantasy palace"],
      "reference_assets": {
        "canonical_scene_plate_path": "",
        "scene_variant_paths": {
          "day": "",
          "night": "",
          "flooded": ""
        },
        "generation_status": "pending | generated | confirmed"
      }
    }
  ]
}
```

## 3. Scene Plate 生成规则

scene plate 应尽量不含主要角色，重点锁定：

- 空间结构和动线
- 主光方向和时间
- 色彩范围
- 核心道具
- 天气、烟、雨、雪、水位等连续性状态

## 4. 执行故事板引用规则

每个执行故事板 panel 必须记录：

- `sceneId`
- `scenePlateAlias`
- `scenePlatePath`
- `inputImagesActuallyUsed` 中实际提交的 scene plate

缺少 scene plate 时，执行故事板可以生成提示词草案，但不能标记为 `verified_identity_scene_layout`。

## 5. 校验规则

视觉验证至少检查：

- 地点是否与 scene plate 一致
- 光线和天气是否一致
- 核心道具是否保留
- 空间关系是否未被重发明
- 是否出现未登记的现代物件或无关风格
