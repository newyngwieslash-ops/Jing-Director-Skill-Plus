> 历史V3构建记录，非4.0.0执行指令或当前验证结论。当前入口见SKILL.md，安装见README.zh-CN.md，合并见docs/MERGE_REPORT.zh-CN.md。

# 独立命名重构记录

日期：2026-09-24。目标：新旧技能可以独立安装、显式选择，不再让新版复用旧调用名。

## 基线与身份

基线是本对话实际附件shanyin-director-master-2-v3.0.0.zip，不是重新生成的缩水替代包。
先解压并逐项验证原PACKAGE_MANIFEST.json，再做改动。新根目录、frontmatter name、默认调用和安装器目标均为shanyin-director-master-v3。
包版本3.0.1用于区分先前3.0.0包；Director Contract和已有示例schema_version不变，仍是3.0.0，不需要重写生产合同。

## 已改动

- SKILL.md：独立名称、明确调用、不得回退/混用其他安装版本的边界；导演生产流程保留。
- agents/openai.yaml：V3展示名、新名默认提示词、Codex默认显式调用策略。
- scripts/install_skill.py：独立目标、Codex/ZCode/both、包校验、重复安装跳过、只升级V3、完整备份/失败恢复；不提供迁移旧名选项。
- install.ps1：转发新安装参数，默认both；不修改执行策略，不运行旧迁移命令。
- scripts/director_pipeline.py：CLI说明和--version报告新技能/包版本，并独立显示旧合同格式版本。
- README、CHANGELOG、UPGRADE_REPORT、安装提示词、project-state模板：统一现行命名与并存策略。
- 测试与发布清单：替换旧迁移测试，增加并存/两端/失败保护测试，重新计算文件哈希。

## 特意不改变

scripts/director_core.py、scripts/director_render.py、所有references、profiles、schemas、镜9examples均按基线字节保留。
legacy的20个历史文件及ORIGINAL_PRESERVATION.json保留；历史来源和备份文中的旧名字不是活动入口。
前版TEST_REPORT/UPGRADE_REPORT/测试日志保存在docs/history，文件名不是SKILL.md，不会作为本版活动技能。
不增加视频模型API、自动生图或白模执行器，不改变对白、镜号、时长或角色资料。

## 不触碰本机旧版

本次只在构建容器内生成新包，未连接用户Windows。运行新安装器也只操作新名字目标；master-2/master-3目录不属于升级对象。
对同名V3升级的备份位于扫描目录之外。若用户此前已经用旧安装器替换旧版，本包不会假装自动恢复它，需要核对用户本机原备份。

## 验证边界

实际测试和包内容比对见TEST_REPORT.md、RENAME_AUDIT.json和test-results.txt。
离线模拟安装不等于真实Windows客户端发现；也不能保证所有Agent都遵守Codex的显式调用配置。
同一电影项目不应并发让两个版本改写同一组输出；新名称解决身份/安装冲突，不替代项目文件的版本与并发控制。

