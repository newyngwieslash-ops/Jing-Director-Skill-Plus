# 原Seedance2步骤8兼容入口

本文件保留旧文件名，方便已存在的工作流引用。现行执行读取 `references/seedance-adapter.md`、`references/director-shot-contract.md` 和 `references/tooling-and-qa.md`。

旧版“每条≤15秒、2000字符”的兼容需求由`profiles/seedance-2.0.json`承载，不再把这些数值硬套到Seedance2.5/H3所有入口。不凑时长，不要求8帧，不截断过长prompt。

输入从Director Contract读取，真实参考从upload_plan绑定；字符预算、已生成、已上传、已过审必须分别记录。旧`legacy/scripts/generate-seedance2-video-storyboards.mjs`仅存档，不是当前默认执行器，其原CLI参数不与新Python命令兼容。
