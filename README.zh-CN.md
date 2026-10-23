> 4.5新增：部门参数卡、可观察表演、F1–F19修复账本、能力路由、声音/剪辑计划与离线行为评估；保留4.4保真与空间交付。入口见[方法层快速上手](docs/METHOD_LAYER_QUICKSTART.zh-CN.md)，来源与边界见[吸收说明](docs/DIRECTORSKILL_ABSORPTION.zh-CN.md)。没有接通真实模型或后期执行器。
>
> GitHub仓库名 `Jing-Director-Skill-Plus` 对应内部技能名 `jingstudio`。整包不同来源的权利分别适用，非统一MIT发行。

> 4.4新增：项目级固定角色颜色、短编号与辅助标识，登记版本绑定和视觉冲突校验。规则见 [角色视觉标识规范](docs/CHARACTER_VISUAL_IDENTITY.zh-CN.md)，完整空间交付见 [使用说明](docs/BLOCKING_COMPLETE.zh-CN.md)。

> 4.3新增：完整场景总览＋逐镜首末站位＋走位＋严格覆盖清单，并通过PNG接入设计板。使用与范围见 [完整空间交付](docs/BLOCKING_COMPLETE.zh-CN.md)。旧示例与历史记录不等于真实项目已批准。

# JingStudio 4.5.0

此前4.2升级强化内容保真和审核证据，并新增确定性XLSX导出、无切点长镜审阅分页和3840×2160三栏设计板；旧样例保留未批准草稿身份。迁移与兼容边界见 [迁移说明](docs/INTEGRITY_MIGRATION.zh-CN.md)。

一个技能包，两条入口：**新剧本→完整导演分镜**；**已有分镜→导演增强与视频输入包**。
4.1新增每场景实际站位图＋走位图、全镜覆盖及路径连续性校验、剧情与看图审核协议；不依赖生图API或film-blocking另行安装。
技能名与目录名均为 `jingstudio`，Director Contract schema仍为3.0.0。
已融合master-2和master-v3，无需安装这两版，也不依赖ponytail或编剧技能。

## 为什么合并

V3已继承旧版前六步和主要参考资料，同时增加导演合同、空间连续性、时间关键帧和Seedance/H3独立编译器。双入口容易混用暂停、时长和图片输入规则。本版补齐旧版设计板规范与角色校验入口，并统一交付范围。详细映射见 [合并报告](docs/MERGE_REPORT.zh-CN.md)。

## 安装到其他Agent

1. 把ZIP传给目标电脑并解压，进入包含 `SKILL.md`、`VERSION`、`scripts` 的 `jingstudio` 目录。
2. Python 3.10+用于离线脚本。Windows用 `python` 或 `py -3`，macOS/Linux通常用 `python3`。安装器不联网、不装依赖、不配置API密钥。
3. 从解压目录执行以下命令，不从已安装目录向自身安装。**必须复制整个包，不能只复制SKILL.md。**

```powershell
python -X utf8 scripts/install_skill.py --verify-package
python -X utf8 scripts/install_skill.py --agent codex --dry-run
python -X utf8 scripts/install_skill.py --agent codex
```

| 目标Agent | 安装命令（任选） | 当前用户默认目录 | 调用 |
|---|---|---|---|
| Codex | `python -X utf8 scripts/install_skill.py --agent codex` | `~/.agents/skills/jingstudio/` | `$jingstudio` |
| ZCode内置Agent | `python -X utf8 scripts/install_skill.py --agent zcode` | `~/.zcode/skills/jingstudio/` | `$jingstudio` |
| Claude Code | `python -X utf8 scripts/install_skill.py --agent claude` | `~/.claude/skills/jingstudio/` | `/jingstudio` |

`--agent both`仅安装Codex+ZCode，不包括Claude Code。PowerShell也可用 `./install.ps1 -Agent claude -DryRun` 再去掉 `-DryRun`；若PS1受限，直接用Python，不改变系统执行策略。

路径依据2026-09-28核对的官方说明：[Codex](https://learn.chatgpt.com/docs/build-skills)、[ZCode](https://zcode.z.ai/cn/docs/skill)、[Claude Code](https://code.claude.com/docs/en/skills)。`~`指运行安装器的用户主目录；WSL、SSH、容器及云端目录彼此独立。

安装后刷新技能或启动新会话，确认显示“JingStudio”。Codex保留V3显式调用策略，避免与旧技能误选；其他客户端按其自身规则发现/启用。文件校验成功不等于客户端已加载。

### 项目级与其他Agent

在技能解压目录中指定集合根目录；将示例路径换成实际项目：

```powershell
python -X utf8 scripts/install_skill.py --agent codex --target-root "D:/film-project/.agents/skills" --dry-run
python -X utf8 scripts/install_skill.py --agent codex --target-root "D:/film-project/.agents/skills"
python -X utf8 scripts/install_skill.py --agent claude --target-root "D:/film-project/.claude/skills"
```

`--target-root`不能包括末尾技能名，不能指向旧技能内部。不要同时安装同名项目版与全局版来赌优先级。安装器仅检查Codex两种常见全局目录，不能穷举所有客户端来源。

其他支持Agent Skills格式的工具：核对其官方目录，复制整个包并保持相对位置。无原生技能发现、但能读文件/运行命令的Agent，可显式要求先读取本包SKILL.md和按需参考；这属于文件加载，不等同于已安装原生技能。只支持粘贴提示词的Agent无法完整运行文件校验和媒体工具流程。

### 更新与旧版处理

- 首次安装新名字，保留master-2、master-3、master-v3原件。
- 同内容重复安装只校验。已有同名包内容不同默认停止；确定升级统一版时用 `--upgrade`，先备份再替换，普通失败尝试回滚。
- 备份目录为 `~/.jingstudio-skill-backups/<时间>/<agent>/jingstudio/`。
- 验证新包后可在客户端禁用旧版，日常只调用统一名；需要移除旧版时先备份到技能扫描目录之外。安装器不删除旧技能。
- 不把新包混盖进旧版文件夹，不把legacy单独安装。

升级例子：`python -X utf8 scripts/install_skill.py --agent claude --upgrade`。
恢复：关闭客户端，将当前同名包移出扫描目录，完整复制日志中的备份回原路径，重启确认。断电/强杀不在普通异常回滚保证内。

## 首次调用

新剧本：

```text
$jingstudio
读取当前项目剧本。自主完成导演定调、双轨节奏、角色与场景档案、九列分镜表和Excel。
已有设定优先继承；缺生图工具先交文本与缺图清单，不伪造图片。
保持核心剧情和对白；真正冲突列明。作品写到当前项目，不写进技能目录。
```

已有分镜：

```text
$jingstudio
读取项目分镜.xlsx及角色、场景和已批准故事板，走已有分镜增强入口。
保留原镜号、镜序、时长、对白和剧情，只处理指定镜头并核对前后动作链。
完成导演合同、连续性、时间节拍、关键帧任务及16:9三栏设计板方案。
先交方案等我通过；真实生图时提交实际参考图。最终只需我指定版本的Seedance提示词包。
```

Claude Code第一行改成 `/jingstudio`。Agent按技能填写JSON并运行校验，无需用户逐字段手填。

## 能力与工具要求

| 交付 | 实现/要求 |
|---|---|
| 定调、节奏、分镜、角色/场景档案 | Agent按随包方法与六类风格库执行 |
| 九列XLSX导出 | 新export-xlsx命令，标准库OOXML并实际回读校验；规范列导出，不复制原工作簿所有样式/页签 |
| 导入、合同校验、分组、文本编译、HTML | 核心使用Python标准库；真实图片的完整性检查需已安装Pillow |
| 完整空间图与覆盖清单 | 每场总览＋每镜entry/exit/movement SVG和PNG；独立roster与项目角色视觉登记严格核对，Pillow/中文字体绘制PNG |
| 剧情关联/连续性/实际图审 | 自动结构检查＋Agent逐镜源文核对和实看双图，分别保存证据；程序不自动认证语义 |
| 角色档案预检 | 可选Node，scripts/validate-character-bible.mjs，无npm |
| 三视图、场景图、逐格画面 | 目标Agent需图像工具及真实参考输入能力；本包不附带模型 |
| 四列详细审阅HTML/PNG | 内置render；PNG可选已有Pillow及中文字体 |
| 16:9三栏设计板 | render --layout design-board --require-blocking；完整空间bundle的PNG自动接入，仍需Pillow/本地中文字体 |
| Seedance/H3 prompt+manifest | 独立离线编译；真实视频需目标Agent的服务/授权 |
| 完整Schema校验 | 可选已有jsonschema；基础语义检查不需要它 |

模型profile是随包基线，不保证目标供应商当前开放相同参数；投产前核对实际版本/接口。不要自动调用视频或安装依赖来验收技能。

## 离线验收

完整空间图示例（两场三镜，包含静止、绕桌行走和无人空镜）：

```powershell
python -X utf8 scripts/director_blocking.py examples/blocking-demo/blocking-spec.json --contract examples/blocking-demo/director-contract.json --roster examples/blocking-demo/roster.json --identity-registry examples/blocking-demo/identity-registry.json --out-dir ../blocking-demo-output
```

打开输出index.html查看场景总览及每镜entry/exit/movement SVG和PNG；4.4不再生成旧场景聚合双图；历史文件仅供追溯。程序通过后仍需按 [逐场景审核规范](references/scene-blocking.md)核对剧情和看图；不能仅凭命令成功声称导演方案已获批准。

直接调用示例：

```text
$jingstudio
读取当前项目剧本、分镜和角色/场景档案。为本次输入的每个场景输出具体角色站位图和走位图。
覆盖全部原镜，空镜和不移动场景也出图。读取项目级角色视觉登记，跨场保持角色短编号、颜色与辅助符号一致。站位标首末状态，路线标方向、时段和原文依据。
实际看图，审核剧情关联、人数去向、障碍通行和前后连续性；记录问题并修正，不用结构通过冒充剧情通过。
场景尺寸未知时标相对示意，不编造实测数据；不改已批准镜号、时长、对白与事件顺序。
```

已有旧统一版安装时，从新4.4.0解压目录运行 `python -X utf8 scripts/install_skill.py --agent codex --upgrade`，替换codex为目标端即可。先备份，仅更新统一版，保留原master-2和master-v3。

从解压包根目录运行，输出写在旁边独立目录：

```powershell
python -X utf8 scripts/install_skill.py --verify-package
python -X utf8 scripts/director_pipeline.py --version
python -X utf8 scripts/director_pipeline.py validate examples/hall-shot-09/director-contract.json --source examples/hall-shot-09/source-excerpt.json
python -X utf8 scripts/director_pipeline.py compile examples/hall-shot-09/director-contract.json --profile minimax-h3 --mode Ref2VA --asset-root examples/hall-shot-09 --out-dir ../jingstudio-demo-output/h3 --draft
python -X utf8 scripts/director_pipeline.py render examples/hall-shot-09/director-contract.json --asset-root examples/hall-shot-09 --out ../jingstudio-demo-output/review.html
```

完整测试：Windows先 `$env:PYTHONUTF8='1'` 再 `python -m unittest discover -s tests -v`，让子进程也以UTF-8处理中文；macOS/Linux用 `PYTHONUTF8=1 python3 -m unittest discover -s tests -v`。样例缺真实图片，预期为draft_missing_assets和缺图审阅页，不证明真实出片。

可转交的安装提示词：[INSTALL_AGENT_PROMPT.zh-CN.md](docs/INSTALL_AGENT_PROMPT.zh-CN.md)。新导出与分页用法：[DELIVERY_GUIDE.zh-CN.md](docs/DELIVERY_GUIDE.zh-CN.md)。当前测试范围：[TEST_REPORT.md](docs/TEST_REPORT.md)。历史记录不代表本次测试。

