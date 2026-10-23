# 4.4 完整空间图、角色标识与设计板

## 本次交付范围

独立输出每场总览、每镜起始站位、每镜结束站位、每镜走位及逐镜覆盖清单。每张图同时提供SVG与PNG，不依赖SVG转换器。当前包补齐两个示例合同的全部场景与镜头：演示2场3镜，展厅1场1镜。不是未提供的完整剧本，也不把展厅上下文镜8/10/11计作当前合同镜头。

场景总览明确采用本场第一镜的起始状态，不把所有镜头的人物位置叠成同一时刻。图中采用示意坐标时，不代表实测尺寸、实际跑速或用户批准。无真实依据的机位不编造。

## 人物基线与阻断

roster.json与blocking-spec.json分开保管，均绑定当前director-contract摘要。roster逐项分类合同subjects：individual、group或non_character。群体必须展开为独立稳定成员ID，并给出expected_count与逐字来源引文。无名员工/游客编号只是跟踪标识，不是编造人名。没有明确分类、缺场、缺镜、少一名角色、缺首末状态、群体人数不符、重复成员或摘要失效都阻断输出。

每场的全部登记人物必须在该场每镜中有明确状态，画外人物不能直接删除。空镜仍保留场/镜和明确零人物记录。原文未包含的人物、被同时篡改的合同/基线、自然语言分类真伪不可能由本地字段检查完全认证；仍需人工核对剧情与人员名单，不把声明当身份认证。

## 项目角色视觉标识

先建立独立的identity-registry.json，角色ID绑定项目固定短编号、颜色、标记形状和路径样式。完整字段与迁移规则见[角色视觉标识规范](CHARACTER_VISUAL_IDENTITY.zh-CN.md)。blocking-spec.json增加identity_binding，绑定project_id、revision和登记表的规范JSON摘要；cast.color须与登记值一致。登记缺失、短编号重复、未登记人物、映射不符、同场相同颜色且相同标记形状的组合或过期绑定阻断；仅路径样式不同不能豁免。近似色等风险仍需看图复核。

## 生成命令

```sh
python scripts/director_blocking.py 项目/blocking-spec.json --contract 项目/director-contract.json --roster 项目/roster.json --identity-registry 项目/identity-registry.json --out-dir 项目/blocking-v1 --font 本地中文字体.ttf
```

输出目录必须不存在或为空，--overwrite不允许混合已有产物。先结构校验，再临时目录构建，完成后发布。失败不产生成功清单。Pillow和本地中文字体必须已经可用，不自动安装。Windows可显式指定C:/Windows/Fonts/msyh.ttc；本轮只在Linux验证。

输出包含每场overview.svg/png、每镜entry.svg/png、exit.svg/png、movement.svg/png，4.4不再生成旧场景聚合positions/movement SVG，以避免第二套身份渲染规则。index.html可点击查看全部图件；coverage.json逐镜列出期望/实际人物、首末状态、路径覆盖和问题；manifest.json绑定输出、来源、人物基线、空间规格及角色登记快照的摘要。

## 接入三栏设计板

设计规格design-spec.json增加blocking_bundle：manifest_path为项目内相对路径，manifest_sha256为该manifest实际文件字节SHA256。另需identity_registry_path和identity_registry_sha256，分别指向项目当前登记表的项目内相对路径及其实际文件字节SHA256。当前登记表须位于图包目录之外；图包内登记快照必须与当前登记表一致，不能只让旧包内部自洽。它独立绑定合同，不需要把新图塞进contract.assets而导致合同摘要循环变化。

```sh
python scripts/director_pipeline.py render 项目/director-contract.json --layout design-board --asset-root 项目 --design-spec 项目/design-spec.json --require-blocking --format both --out-dir 项目/design-spatial-v1 --font 本地中文字体.ttf
```

严格模式缺bundle立即失败；给定bundle后检查全合同的场景与镜头，不只检查当前审阅窗口。程序重算严格覆盖，核对当前角色视觉登记及图包快照、角色基线/规格/覆盖清单、所有登记文件和图像摘要，再将本场总览与对应镜头首末/走位PNG放入中栏，长内容完整续页。缺任意图、错镜映射、过期或删改图文件都会阻断。

不带bundle的旧版设计板仍可输出，但明确spatial_incomplete，不能当完整空间交付。完整空间图的状态为spatial_complete_schematic，仅说明图件与结构覆盖完整；整体仍draft与needs_manual_review，不伪造用户批准或影片验证。

## 本轮示例入口

- examples/blocking-demo/blocking-complete/index.html：两场三镜，包括无人空镜。
- examples/hall-shot-09/blocking-complete/index.html：展厅镜9，六个subject展开十人，补齐独立站位走位图。
- 两个示例的design-spatial/index.html：实际接入完整空间PNG的三栏设计板。
- 原compiled/、preview/等历史草稿保留追溯；其中旧配色/局部P编号不是4.4当前交付入口，不因新空间图存在就升级成生产批准。

## 审核边界

图示不进行3D人体碰撞、动态避障、视线可见性求解、实测场地复核或影片生成。示例的艺术/空间提议待用户复核。真实项目仍需提供完整已批准镜表、角色与场景材料，工具才可能生成对应完整图件；不能对未知输入宣称全项目齐备。
