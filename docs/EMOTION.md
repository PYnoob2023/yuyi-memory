# 独立情绪模块

常态基线 B 不自动改写，短期 S 默认半衰期 2 小时，长期 M 默认 72 小时。事件由宿主模型评估，代码按真实经过时间维护状态：

```text
w = intensity × confidence
S += short_gain × w × impact
M += mood_gain × w × impact
S/M 按各自半衰期指数衰减
坐标 = tanh(atanh(B) + S + M)
```

三个轴均为 -1..1：pleasure、arousal、agency。贡献有上限。tentative 解释只留下 0.35 倍短期影响，长期贡献为零；低置信度、未知结果、自动检索旧事和他人的情绪不计入助手状态。正负影响量分别保留，支持复杂感受。

十种原型词区结合事件解释生成候选；委屈等词有语境门槛，边界使用滞回。词区与权重是工程表示，不是心理诊断或经过校准的概率。EmotionAtlas 可导出 9×9×9 候选数组，运行表达仍按连续距离计算。

## 使用

```sh
python -m yuyi_emotion --db data/demo-emotion.sqlite3 init
python -m yuyi_emotion --db data/demo-emotion.sqlite3 event examples/emotion/shared_success.json
python -m yuyi_emotion --db data/demo-emotion.sqlite3 status --at "2026-11-03T00:00:00+09:00"
python -m yuyi_emotion --db data/demo-emotion.sqlite3 audit
python -m yuyi_emotion --db data/demo-emotion.sqlite3 retract demo-success-001 --reason correction
python -m yuyi_emotion --db data/demo-emotion.sqlite3 restore demo-success-001
python -m yuyi_emotion --db data/demo-emotion.sqlite3 replay --at "2026-11-03T00:00:00+09:00"
python -m yuyi_emotion atlas --resolution 9 > emotion-atlas.json
```

示例是固定历史时间，使用新的演示库。Python API 接受 Unix 秒；CLI 还接受带时区 ISO 日期。迟到事件会拒绝，历史回放应按时间排序进入独立库。

事件 source ID、工具 verified 标记由宿主提供，模型不能自行设置。评估回调及示例见 examples/emotion/host_integration.py。数据库只接收结构化评估，context 不另存为聊天记录；不要把正文当作 ID。模型仍可能解释错，需要真实对话检查。

读取状态不写入、不强化。事件与来源去重，撤回重算包含后续饱和影响；撤回不是物理删除。恢复必须显式审阅。配置哈希或助手身份不同则拒绝打开，不静默迁移。backup 使用 SQLite API 且不覆盖现有备份。

输出只是语气、节奏、玩笑程度的参考，不强制回复台词，不要求宣布数值或向用户索取安慰；不能保证任意模型遵守。当前没有改记忆、自我模型或人设，也没有自动后台行为。
