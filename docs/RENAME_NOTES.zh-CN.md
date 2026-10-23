# JingStudio：名称、安装与旧版并存

当前显示品牌为 **JingStudio**，技能标识与安装目录为 **`jingstudio`**，包版本 **4.5.0**。仓库名 `Jing-Director-Skill-Plus` 不等于技能目录名。Director Contract 仍为3.0.0；人物标识、剧本、示例合同、图示及已批准内容不会因品牌改名而迁移或重写。

## 安装与调用

ZIP 解压或 Git clone 均可安装。安装校验与复制只忽略包根目录的 Git 元数据（`.git` 目录或 worktree 指针文件），不复制该元数据；链接形式的 `.git` 仍拒绝，普通未声明文件仍阻断。

解压后进入 `jingstudio/`（内含 `SKILL.md` 与 `scripts/`）。从仓库下载的源代码目录如带有仓库名，可将包含这些文件的整个包目录命名为 `jingstudio`，不要只复制入口文件。

```bash
python -X utf8 scripts/install_skill.py --verify-package
python -X utf8 scripts/install_skill.py --agent codex --dry-run
python -X utf8 scripts/install_skill.py --agent codex
```

| 客户端 | 安装参数 | 新安装目录 | 显式调用 |
|---|---|---|---|
| Codex | `--agent codex` | `~/.agents/skills/jingstudio/` | `$jingstudio` |
| ZCode | `--agent zcode` | `~/.zcode/skills/jingstudio/` | `$jingstudio` |
| Claude Code | `--agent claude` | `~/.claude/skills/jingstudio/` | `/jingstudio` |

安装器校验成功只证明文件部署正确，不证明客户端发现或加载；请刷新技能或开启新会话后核对显示名称。当前工具不调用真实模型。

## 与旧版并存，不自动迁移

所有旧版安装保持原位、原名称与原内容。安装器只创建 `jingstudio`，不会把旧目录重命名、覆盖、卸载或迁入新目录。旧版目录及其子目录不可作为 `--target-root`；该参数应指向技能集合目录。若已有旧技能被人工改名放进 `jingstudio`，即使用 `--upgrade` 也会拒绝覆盖。不要手动改旧版入口冒充新版。

新旧版并存时显式调用新标识，避免误选；旧版项目与自定义内容需人工审查后单独迁移，不由本安装器自动合并。

## 重复安装与升级

相同包重复安装为无修改操作。只有现有 `jingstudio` 内容不同且明确提供 `--upgrade` 才升级；升级前逐文件备份校验，备份位于 `~/.jingstudio-skill-backups/<时间>/<agent>/jingstudio/`。每次升级独立备份，普通中途失败会回滚；旧技能不参与升级。不要删除备份，确认需要保留的自定义修改后再处理。

## 来源与历史

当前名称不替代原始作者署名或第三方许可。原件与哈希保留在 `legacy/` 和 `docs/ORIGINAL_PRESERVATION.json`；`docs/history/` 是历史证据，不是当前安装指南或测试结论。历史出现的旧名称仅用于追溯。原作者、上游方法及授权边界见 [权利说明](../THIRD_PARTY_NOTICES.md) 与 [来源](SOURCES.md)。
