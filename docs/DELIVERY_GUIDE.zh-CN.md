> 4.4完整空间交付还需项目级角色视觉标识登记与当前版本绑定，不能仅沿用旧cast.color。规则见 [角色视觉标识规范](CHARACTER_VISUAL_IDENTITY.zh-CN.md)，当前命令见 [完整空间交付](BLOCKING_COMPLETE.zh-CN.md)。

> 4.3新增严格完整空间bundle，自动将其原生PNG纳入设计板；无需手动把SVG栅格化。本页4.2任意SVG输入的限制仍成立。完整空间交付请读BLOCKING_COMPLETE.zh-CN.md并使用--require-blocking。

# 4.2 导出与设计板使用说明

本版离线工具不调用模型、不生成新镜头画面。以下命令从技能根目录运行，输出应放在项目独立目录，不覆盖源文件。没有实际图像与审图证据时，结果仍是待审核草稿。

## 九列XLSX导出

```sh
python scripts/director_pipeline.py export-xlsx 项目/source.json --out 项目/分镜表.xlsx --report 项目/export-check.json
```

输入为 ingest 产生的来源快照，不是导演合同。规范九列按原镜顺序导出；源有视频提示词时加第十列。原 raw_cells 存在时保留原文空白与换行，没有时只保证已归一化字段，报告列出差异范围。未知非空列、非法XML字符、超长单元格或来源不一致会阻断，不截断、不偷偷丢列。所有文本作为字符串，类似公式的文本不执行。为防Excel把字面 `_xHHHH_` 当转义，当前版本明确拒绝此类保留序列，不偷偷修改原文。

输出先实际通过 ingest 与底层表格读取回读；验证每列原文、顺序、时长与总长，再发布文件与检查报告。相同输入和配置产生字节一致XLSX。它不是原Excel样式/所有sheet/公式的无损复制器。软件回读通过不等于已在用户Excel中逐页看过。

## 不切镜长镜分页

```sh
python scripts/director_pipeline.py group 项目/director-contract.json --pagination no-cut --out 项目/review-plan.json
```

旧 group 默认行为保留；新策略明确用 --pagination no-cut。单镜超过人审板时长上限时生成审阅时间窗，优先beat边界，否则使用明确审阅边界。原shot_id、原时长、事件与关键帧不变，分页不是电影切点，不会让超出模型时长上限的镜头绕过生产限制。

需要指定窗口时用 --windows 指向窗口JSON，必须完整覆盖原镜时间、无重叠、无空洞、按源顺序。对白跨窗显示完整原项并标注上下文，不按字数伪造时间。图像不存在于窗口边界时标缺图，不拿结尾图替代中间时间。

## 三栏设计板

```sh
python scripts/director_pipeline.py render 项目/director-contract.json --layout design-board --asset-root 项目 --review-plan 项目/review-plan.json --design-spec 项目/design-spec.json --format both --out-dir 项目/review/design-v1 --font 本地中文字体.ttf
```

--review-plan 和 --design-spec 可省略；没有显式参考映射时左中栏显示缺图。固定3840×2160画板，左角色参考、中场景和空间参考、右时间关键帧/动作/对白。影片本身可为其他比例，图像按contain显示不强行拉伸。长内容通过版面续页完整呈现，续页不增加视频时长。旧 --out review.html 的四列审阅功能保留。新设计板仅写入不存在或为空的输出目录；即使加 --overwrite 也不覆盖非空目录，请使用新版本目录，防止失败混合新旧产物。

新布局需要已安装Pillow及本地中文字体，包括HTML布局测量；不自动下载或安装。栅格图片使用PNG/JPEG/WebP。当前SVG不能自动转换为PNG，必须提供真实栅格预览，否则明确占位并在manifest记录未完成项，不能宣称空间图已经完整进入设计板。

设计规格schema为design-board-spec-1，contract_sha256必须等于当前合同的规范JSON摘要。scenes按scene_id映射，支持character_asset_ids列表、plate_asset_id、blocking_asset_ids列表，均引用合同assets中的image资产。未知字段报错而非静默忽略。可选footer包含tone、character_dynamics、cinematic_approach，每项使用 {"source_pointer":"/project/style/zh"} 形式的RFC6901指针，必须指向绑定合同内的字符串。缺字段显示待定；长内容在中栏无损续页，不伪造批准。

设计板manifest记录输入摘要、页与时间窗对应、文本片段覆盖、缺失项、输出摘要及needs_manual_review。图片已经被替换或审核证据缺失时，审阅标签不得显示为当前已审通过。整体看图、剧情与最终视频验收仍需独立完成。

## 真实模型服务

本包目前仅离线prompt与上传计划；不把指导profile当真实API。服务接入阶段需用户确认供应商、实际model_id、API文档、输入槽位与预算，再通过安全方式配置密钥。未选择服务前，不伪造网络适配完成，也不发送付费请求。

## 资源上限

no-cut计划最多10000个窗口和片段，过小分页上限造成超预算时明确拒绝。设计板最多1000页、50000内容项、100万文本字符，单图上限4000万像素；超限时请按独立项目批次处理，不自动删减。
