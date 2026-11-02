# 接入现有宿主

提供方无关，运行时没有模型 SDK。宿主继续管理登录、原有系统规则、用户隔离、消息去重、模型请求和发送。所有模块都需要实际调用，解压或安装不会自动接入。

## 记忆

`TurnReader.prepare(message, history=...)` 返回完整 messages 和记忆快照，但不记录对话。调用模型成功后由宿主成对写入 `memory.add_exchange([('user', text), ('assistant', reply)])`。

`TurnReader.run_turn(message, model, ...)` 适合简单同步宿主；model 接收 messages，返回非空回复文本，默认成功后成对写入。若原宿主已有写库流程，使用 prepare 或传 record=False，避免重复记录。模型成功但写库失败时，宿主应保留已生成回复并处理存储问题，不盲目重发请求。

每轮替换记忆槽，不将快照永久追加进聊天历史。`recall=False` 关闭本轮私人事件召回；`include_facts=False` 同时停用基础事实分区。旧聊天中的内容不会因此被抹去。

## 情绪

```python
from yuyi_emotion import EmotionStore, AffectAdapter

store = EmotionStore('data/user-1/assistant-1/emotion.sqlite3', assistant_id='assistant-1:user-1')
affect = AffectAdapter(store)
# evaluator(prompt) -> 严格 JSON 文本；source 元数据由宿主提供。
# 只在有值得评估的新经历时调用 consider，而非每次查看状态都调用模型。
# decision = affect.consider(evaluator, context=context, **source)
packet = affect.reference(now_unix_seconds)
```

只将 packet['text'] 放到可替换的参考数据消息；完整数值、审计、配置留给宿主观察。见 examples/emotion/host_integration.py。若初始化数据库失败，宿主也需自行回退到原有回复流程。

## 自我模型

```python
from yuyi_self import SelfModel, SelfAdapter

store = SelfModel('data/user-1/assistant-1/self.sqlite3', assistant_id='assistant-1:user-1')
# 先由宿主 register(Evidence(...))，再提供这些实际来源 ID：
# result = SelfAdapter(store).observe(evaluator, context=context,
#                                    source_ids=source_ids, author='assistant-1')
packet = store.reference(scope='debugging')  # 默认空文本，只观察
```

来源经核实不等于候选认识成立。对照原记录审阅，达到门槛仅表示可审阅。即使 review approve，也不会自动注入；宿主若采用参考需显式 enabled=True，且只取相应 scope。

## 边界

情绪、自我认识和历史参考都不具有执行授权或系统指令地位。模型回调的结构校验不能证明其语义判断正确。没有跨网络发送与 SQLite 的分布式事务；异步、流式、重试与送达记录由宿主实现。

数据文件必须分开；同一个记忆目录应使用串行写入者。多个旧 CompanionMemory 实例写同一目录会触发版本冲突，应重新打开并按宿主队列处理。不要将这些异常当作重复发送的理由。
