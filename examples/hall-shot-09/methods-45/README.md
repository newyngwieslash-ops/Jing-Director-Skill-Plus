# 4.5 离线方法示例：可审核草案，不是成片执行结果

入口：[方法审核页](review/method-review.html) · [实际校验报告](review/method-report.json) · [结构化方法包](method-pack.json)

## 如何读

- `locked_source` 是本目录现有合同逐镜快照，`contract_sha256` 绑定该合同；它不独立证明原始剧本真实性。源文件、人物清单、身份表、站位图与设计板均未因方法包而修改。
- `source` 注释逐字引用合同字符串，并附 JSON Pointer 和原值；这只表示**合同层来源**，不把此前导演推导升级成剧本原话。
- `inference` 全部是待确认建议，没有创作审批效力；`unknown` 保持空文本。部门卡反例是禁止越权的边界，不是源镜新增情节。
- 每个表演记录中的 task 是引用该 beat 的**全场上下文**，不是要求每个角色执行引文里的全部动作。角色范围以 role_id 确定；群组细分和逐个站位仍以原 roster、identity registry 和空间覆盖检查为准。
- 源声音 cue 引文与提议的声部分离并列用于审核，**不是同时叠加播放的混音列表**。提议分层、声像、触点精确时序尚待真实素材和人工确认；asset_ref 均为空。
- RT/AMB/FOL/SFX/MUS 是计划分类；不为凑满五层新增声响。原合同无画外配乐，所以 MUS 不生成 cue。无对白即保留空对白，不把笑声编成台词。
- 24 fps 是这份离线计划选择的整数时基，使用半开区间 [in, out)。没有实际生成素材/NLE 时间线，source_in/out 仅是合同内计划区间，不是已验证媒体入出点。
- 没有角色成图、审核通过记录、供应商能力证据、真实模型调用、生成 take、花费或修复执行。能力均 unknown，首尾参考为空，execution_ready=false。

## 修复账本演练（纯假设，不进入 attempts）

假如未来实际成片出现脚底滑移，可先按 F14（物理/重量反馈）诊断；假如本应固定的镜头继续运动，可按 F6（错误机位运动）诊断。先绑定真实 take、帧范围及证据，再尝试低损耗提示修正，不许在没有素材时声称已检出故障。

算例仅用于理解双计数：假设同设计两次失败、随后另一设计一次失败，则全镜累计失败尝试数为3，两个设计失败计数分别为2和1。该算例不代表本项目发生过任何尝试。本包 attempts=[]，实际计数为0；预算12、同设计阈值3是脚手架默认规划上限，不是已批准付费预算或调用授权。达到阈值仅阻断并提议，不自动删镜、拆镜、变更时长或转画外处理。

## 已完成与仍阻断

已完成：六部门规则卡、来源证据绑定、表演注释、声音 cue 草案、逐帧剪辑区间、离线结构检查和静态 HTML 审核输出。

仍阻断：独立源证据认证、推导建议审批、实际素材与参考图证据、供应商能力验证、真实成片效果和声音/剪辑执行。`structurally_valid=true` 只表示通过本方法包校验；`status=draft` 不是正式审核通过。

HTML 已由真实 review 命令产生并做结构/内容解析检查；未宣称浏览器截图或成片视觉审片通过。

## 重跑（从项目根目录）

```bash
python scripts/director_methods.py validate --contract examples/hall-shot-09/director-contract.json --pack examples/hall-shot-09/methods-45/method-pack.json --report /tmp/hall-shot-09-method-validate.json
python scripts/director_methods.py review --contract examples/hall-shot-09/director-contract.json --pack examples/hall-shot-09/methods-45/method-pack.json --out /tmp/hall-shot-09-method-review-new
```

输出目录必须是新目录；不要覆盖既有空间图、设计板或合同。

## 镜9边界

本例只有 S009，10秒/240帧；不代表原工作簿39镜覆盖。合同六个 subject 引用中包含群组，**不是六个人**；独立 roster 的10人为男孩、父亲、四员工、陆宸、尔玛朵、两游客。空间交付仍通过原10人身份表和逐镜覆盖清单核验。

低机位中远景，同轴侧拍，男孩由左向右追单一蓝气球，细线缠腕；摄影机 [0,48) 帧向右跟拍，[48,240) 固定。左后队列与右侧讲解组维持位置；结束时未绊倒、未碰撞，展架与绣面完整。源合同三个 beat 为 [0,48)、[48,168)、[168,240)。镜10/11仅为前瞻来源，不输出新增镜头。

重量/支撑脚/声像建议均为 inference，没有擅自改动起末站位、路线、镜号或时长；成人群组的表演记录不是逐个成员的生成素材或合格证明。
