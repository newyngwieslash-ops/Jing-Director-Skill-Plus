> 4.5新增来源记录见[DirectorSKILL吸收说明](DIRECTORSKILL_ABSORPTION.zh-CN.md)：固定提交c65ae0d14457053efb1e354c7e7f7e120d97fad1、逐模块采用范围和许可。以下V3历史来源保留，不是4.5新验收结论。

> 历史V3构建记录，非4.0.0执行指令或当前验证结论。当前入口见SKILL.md，安装见README.zh-CN.md，合并见docs/MERGE_REPORT.zh-CN.md。

# 来源、采用方式与能力边界

核对日期：2026-09-24。网页为当时读取的main/在线版本，没有固定上游commit；不将可变分支描述成可复现锁定源码。本包未下载/内嵌完整上游Skill。以下URL供人工核对，运行本包不需要联网。

## 1. 你选中的导演路线

- 仓库：https://github.com/62656456/ai-film-skills
- 入口：https://raw.githubusercontent.com/62656456/ai-film-skills/main/skills/ai-storyboard-director/SKILL.md
- 导演引擎：https://raw.githubusercontent.com/62656456/ai-film-skills/main/skills/ai-storyboard-director/references/shot-design-engine.md
- 摄影引擎：https://raw.githubusercontent.com/62656456/ai-film-skills/main/skills/ai-storyboard-director/references/cinematography-design-engine.md
- 空间轴线：https://raw.githubusercontent.com/62656456/ai-film-skills/main/skills/ai-storyboard-director/references/framing-and-axis.md

读取到的入口内部版本为5.6.4；仓库标示Apache-2.0。采用的是“从叙事/调度决定摄影，再检查时间和空间”的工作顺序；本包的Contract、脚本、分组和排版为独立实现，不是调用上游同名引擎。没有强制采用上游默认六段可见母稿，因为用户原项目明确需要Excel、四列审阅板与模型输入包。

## 2. H3提示词指导

- 官方仓库：https://github.com/MiniMax-AI/MiniMax-H3
- Skill入口：https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/SKILL.md
- 基础指导：https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/references/base-en.txt
- 全参考指导：https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/references/ref-en.txt

采用模式分流、基础/全参考字段组织、内容/文件标签分离、原语台词和时间锚点的接口语义。仓库存在社区许可，不能将整个H3仓库/模型误标MIT或Apache。这里仅实现独立prompt编译策略，不分发权重、推理框架、完整官方Skill或官方指南全文。未做供应商生成验证。

## 3. Seedance模型能力

- 官方模型页：https://seed.bytedance.com/en/seedance2_5
- 官方发布说明：https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5

2.5的30秒、扩展参考容量与白模参考方向是模型级资料，不代表每个代理/API/产品模式开放同样能力。profile明确标注实际model_id及供应商尚未绑定。Seedance2.0的旧2000字符项目预算来自原Skill，不作为全平台API硬限。

本包的整数秒请求策略、4秒Seedance最短值、Seedance2.0保守参考数限制是本地生产策略，不冒充最新官方参数。使用前可按真实provider文档调整profile并记录哈希；不能绕过用户的原时长合同。

## 4. Codex本地Skill

- 官方入口：https://developers.openai.com/codex/skills
- 当前页面：https://learn.chatgpt.com/docs/build-skills

采用name/description入口、按需加载参考、可选agents/openai.yaml和用户级`.agents/skills`安装方式。原`.codex/skills`路径只保留为用户既有环境兼容选项；安装脚本不宣称能检测所有Codex宿主扫描规则。

## 5. 用户提供的原材料

原包：`shanyin-director-master-2.rar`；完整逐文件原内容在legacy（原SKILL入口只改文件名，不改字节）。参考故事板Demo与《第一集分镜.xlsx》用于识别实际问题和构造镜9候选例子。原Excel未改动，未随本Skill附上完整剧本；示例仅包含镜9及必要相邻镜原文。

资料权利与模型生成/商业输出权利分开，不能因本包没有收费API代码就推断全部素材可公开再分发。

## 6. 本次独立命名与ZCode安装核对

本次3.0.1仅为身份/安装重构；上方视频模型与导演来源记录沿用基线，并未再次逐项验证模型参数。
2026-09-24重新读取：
- Codex技能与显式调用：https://learn.chatgpt.com/docs/build-skills
- ZCode用户级技能、刷新与调用：https://zcode.z.ai/cn/docs/skill

Codex用户级目录为HOME/.agents/skills；同名技能不自动合并。allow_implicit_invocation=false只作为Codex配置使用。
ZCode内置Agent用户级目录为HOME/.zcode/skills，目录名与frontmatter统一；通过$选择并在设置中刷新。
这些是官方文档默认值，不是已经读取过用户本机配置的证明。安装器不自动跨WSL/SSH安装，也不自动启用客户端设置开关。

