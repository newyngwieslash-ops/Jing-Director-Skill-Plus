# 复制给目标Agent的安装指令

先把ZIP放到目标Agent可访问的环境并解压，替换下方路径与目标（codex/zcode/claude任选，both仅Codex+ZCode）。

```text
请将JingStudio统一导演技能安装到当前环境。
已解压包目录：[绝对路径，例如 D:/Downloads/jingstudio]
目标Agent：[codex / zcode / claude / both，填写一个]

先读取README.zh-CN.md和SKILL.md，确认name为jingstudio，VERSION为4.5.0。
在该解压目录用Python 3.10+运行：
python -X utf8 scripts/install_skill.py --verify-package
python -X utf8 scripts/install_skill.py --agent <目标> --dry-run
预检通过且目标正确后，直接执行同命令去掉--dry-run，完成已授权安装。
不得覆盖、卸载或迁移master-2、master-3、master-v3，不安装依赖，不调用图像或视频API。
同名统一版已存在且不同时，说明差异再询问是否用--upgrade；相同则直接校验。
从目标目录再次运行 --verify-package 和 director_pipeline.py --version，确认实际路径。
用包内样例执行validate；示例缺图不能当作已生成。
最后报告安装路径、版本、校验结果、客户端刷新/调用方法和未验证事项。
明确当前运行环境是Windows/WSL/SSH/容器中的哪一个，不把安装到容器说成安装到了宿主。
```

识别后首条生产消息：

```text
使用JingStudio统一导演技能处理当前项目。读取已批准分镜与参考资产，按现有成果选择入口。
不重做已确认工作，镜号、时长和对白保持不变。列出当前交付、缺失素材与必要冲突。
```

Codex/ZCode前置 `$jingstudio`；Claude Code前置 `/jingstudio`。

