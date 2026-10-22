# Companion Memory v2

一个用于持续相处的虚拟人物的记忆原型。近期事情保持清楚，重要经历留得更久；普通小事可以忘掉。它在模型外部维护记忆，不修改模型参数，也不保证模型永远正确。

## 这一版改了什么

| 部分 | 实现 |
| --- | --- |
| 保存与恢复 | 整体状态由 SQLite 事务提交；记忆更新、清空队列、清除退避一起成功或一起失败 |
| 事实与冲突 | 稳定事实 ID、修订历史、否定和假设的保守检查、冲突进入待确认区 |
| 人物连续性 | 独立记录事件、承诺与关系事件；状态和长期意义分开处理 |
| 联想召回 | 有来源的事件边、原文支持的共同线索，最多两步激活扩展 |
| 遗忘边界 | 模糊阶段保留概要或印象；重要关联事件消失后可留下有限时长的无正文存在标记 |
| 使用边界 | 不主动提起与真正删除分开；主动删除清理关联、待确认项和命中历史 |
| 整理成本 | 保留低频整理与失败退避；可选只读按需检索工具限制调用次数和返回长度 |

这是在最后提供的 19 组测试版本上修改的新项目副本，桌面原文件未动。当前离线测试共 59 项，均在 Python 3.13 本地通过；没有进行真实模型 API 或 QQ 联调。

## 开始运行

需要 Python 3.10+，只使用标准库。请完整解压本文件夹，**不要只复制 companion_memory.py**：它需要同目录的 `legacy_memory.py`，后者复用原有遗忘和字段清洗逻辑。

```sh
python test_memory.py
python demo.py
```

演示不联网、不需要密钥，使用临时目录。`test_memory.py` 同时运行新增回归测试与 `test_legacy.py` 中的兼容性检查；后者只将旧的“冲突直接进候选”断言更新为“冲突进待确认区”，并修正文件句柄关闭。

## 最小使用示例

```python
from companion_memory import CompanionMemory

memory = CompanionMemory("memory_data/qq_private_001", user_title="朋友")

# 以下是可信接入层明确写入已经确认的事件，不要将这两个接口任意交给模型。
illness = memory.remember("那次发烧住院", importance=8)
promise = memory.remember("陪你等天亮", importance=8, kind="promise", relationship=2)
memory.link(illness, promise, "那次发烧住院之后，我们约定陪你等天亮")

print(memory.build_context("还记得发烧住院吗"))
memory.set_status(promise, "fulfilled", "陪你等天亮的承诺已经兑现")
```

`remember()` 返回事件 ID，低重要度被过滤时返回 None。`kind` 可用 event、promise、relationship。`relationship` 为 0..3 的长期关系意义，只调整记忆稳定度；open 状态只在有线索召回时增加少量可及性，不会无条件每轮加载。

`link()` 的证据需要同时提及两端事件并含明确关系线索；它只扩展已有事件，不创造新的共同经历。这仍是保守的字面检查，不能保证理解所有指代或识别所有虚假联系。

## 接到聊天和 QQ

```python
def on_private_message(user_text, chat_model, memory_model):
    # chat_model(messages) -> 回复字符串
    # memory_model(prompt) -> 整理结果的 JSON 字符串
    memory.maybe_consolidate(memory_model)
    messages = [
        {"role": "system", "content": memory.build_context(user_text)},
        *memory.recent_messages(),
        {"role": "user", "content": user_text},
    ]
    reply = chat_model(messages)
    # 双方消息使用同一个事务保存。
    memory.add_exchange([("user", user_text), ("assistant", reply)])
    return reply
```

这是接入顺序示意，聊天和整理函数需由你现有的服务提供。`deepseek_llm()` 仍可用，但要显式传入服务商实际支持的 model、base、api_key；保留的默认模型名没有经过真实接口验证。

每个 QQ 联系人和群使用独立目录。相同会话仍应按顺序处理；异步网关请把同步网络与磁盘操作移到工作线程。本版对象内用锁串行，多个对象同时写同一目录会触发 `ConcurrentUpdateError`，而不会悄悄覆盖：此时重新打开会话，按接入层队列重试，不要重复发送回复。

发送消息、模型调用和 SQLite 之间没有分布式事务。QQ 层仍需要消息 ID 去重与送达记录；本版不提供 QQ 登录、事件循环或完整发送失败恢复。

## 待确认的内容

否定不一致、假设、无法确认目标的删除，以及检测到的当前事实冲突，不进入正常聊天记忆。接入层可读取：

```python
for proposal in memory.list_confirmations():
    print(proposal["id"], proposal["reason"], proposal["value"])

# 仅在用户明确认可该条内容时调用；拒绝则 accept=False。
memory.confirm(proposal_id, accept=True)
```

不要把 confirm 作为模型可以自行使用的工具。模型不能自己批准自己提取的事实。一次明确有效的更正保留原事实 ID，旧状态进入 history，避免把历史状态混作当前事实。

目前居住地、职业、关系和健康领域通过有限中文规则识别，同一用户同一领域有冲突时等待确认。复杂事实、同名人物、多项疾病或多个职业需要更细实体与属性建模，不能依赖本版的简单领域键。

## 状态和关系

承诺的 open 表示尚未确认完成；fulfilled 表示有用户依据确认兑现。关系事件可用 open、resolved；cancelled 表示取消。助手说过承诺不等于用户已确认承诺实现，单方面宣称兑现不能更新状态。

整理输出可额外包含：

```json
{
  "events": [{"text": "陪你等天亮", "importance": 8, "kind": "promise", "relationship": 2, "anchors": ["等天亮"], "src": [2]}],
  "core_updates": [{"fact_id": "已有事实ID", "new": "现在住在大阪", "src": [3]}],
  "status_updates": [{"id": "已有事件ID", "status": "fulfilled", "src": [4]}],
  "links": [{"a": "事件A的ID", "b": "事件B的ID", "relation": "follow_up", "src": [5]}]
}
```

编号对应本次待整理消息，从 1 开始。可建立明确联系的 links 两端必须已经存在；新事件入库后才能通过下一批整理或 `link()` 连接。status_updates 必须引用用户消息。核心更新旧 index 格式仍兼容，但新接入应使用 fact_id。

## 不提起与删除

```python
memory.suppress(event_id)             # 保留，但不作为召回节点或联想桥梁
memory.suppress(event_id, False)      # 允许再次召回
memory.forget("关键词")              # 清理命中内容，近期和待整理原文同步遮蔽
memory.reject_name("不喜欢的称呼")
memory.set_user_title("新的默认称呼")
```

主动删除不会留下对应图边；无正文的存在标记因不能再按关键词精确定位，会全部清空。昵称禁用不再因超过数量限制就自动丢失；默认称呼若被禁用且尚未另设，提示词临时用“你”。

关键词删除不是语义删除，更不是对磁盘、备份、旧 JSON 和 SQLite 空闲页的安全擦除。原始数据的外部副本仍需自己管理。

## 可选的按需记忆工具

`memory_tools.py` 提供供应商无关的 `RECALL_TOOL` 名称、说明和 JSON 参数约束；接入层按所用模型接口包装它。

```python
from memory_tools import RECALL_TOOL, MemoryTools

tools = MemoryTools(memory, max_calls=2)  # 每次回复重新创建一次，由接入层控制
result = tools.run("recall_memory", {"query": "那次生病", "char_budget": 400})
```

返回当前仍能记起的内容，限制最多两次调用，并按序列化字符数控制结果长度。纯工具检索不巩固，也不能删除或确认。预算过小时返回空结果；包装本身有少量固定字符开销。工具结果要由接入层正确放回模型消息，本项目没有冒充已经完成所有供应商的函数调用循环。

主上下文仍可预先放少量线索，与按需检索混合使用；如果完全不提供线索，模型可能不知道需要查询哪段记忆。

## 遗忘机制和新参数

保留原有 R = exp(−t/S) 及清晰、模糊、印象、删除阈值。原稳定度再乘以 `1 + relationship_boost × relationship`，默认 relationship_boost=0.25。没有关系加成、没有巩固时，原来的时间表保持不变。

| 新配置 | 默认 | 含义 |
| --- | --- | --- |
| pending_max | 500 | 超出则报 QueueFullError，不丢旧消息 |
| confirmation_max | 100 | 待确认记录上限，超过保留最新项 |
| association_hops | 2 | 联想扩展步数，允许 0..3 |
| association_decay | 0.65 | 每步激活衰减 |
| association_beam | 20 | 每步保留的扩展节点数 |
| edge_max | 2000 | 图边上限 |
| relationship_boost | 0.25 | 长期意义对稳定度的加成 |
| open_issue_boost | 0.12 | 已被线索召回的未解决事件的排序加成 |
| state_char_budget | 400 | 内部状态片段预算 |
| trace_days | 30 | 观察到关联事件消失后存在标记的保留天数，0 关闭 |
| trace_max | 50 | 无正文存在标记数量上限 |

存在标记仅保存 ID、事件类型和时间，不含主题、正文或关键词，通过 inspect_traces() 供管理层查看，不自动注入人物台词。它不是“知道某个具体秘密却想不起”的生成依据；普通小事仍会彻底退出事件库。

其他默认配置见源码 CONFIG。往事仍默认最多 5 条、1200 字符；人设、核心事实、近期原文和工具结果并无统一 token 预算。没有实现连续向量软记忆、真实语义嵌入或完整的总上下文分页调度。

## 文件和迁移

- `companion_memory.py`：新版入口、事务、来源门控与联想。
- `legacy_memory.py`：内部复用的原版算法，**不要直接用它创建生产会话**。
- `memory_tools.py`：可选的只读检索工具。
- `demo.py`：离线承诺与联想演示。
- `test_memory.py`、`test_legacy.py`：新增与兼容性回归测试。
- `MIGRATION.md`：迁移、备份与失败恢复说明。

首次打开只有旧 JSON 的目录时自动导入，成功后 SQLite 成为唯一权威状态，不再更新原 JSON。已有 persona.md 不覆盖。请先在副本上测试迁移，不要让旧版和新版同时操作同一份数据。具体步骤见 MIGRATION.md。

## 仍需说明的限制

- 语义门控仍是保守启发式，防住测试中的否定和无关删除，不代表解决全部事实一致性问题。
- 没有对所有同义表达、反讽、代词、多人物身份进行可靠解析；联想边检查也可能误收或漏收。
- 关系意义由来源约束加模型提取或可信调用方指定，不是经过验证的情感测量。
- 关联图只有已有事件与字面线索，没有借概念常识补全事实；检索效果需真实长期对话评估。
- SQLite 提交与内存回滚已测试；持续磁盘故障时连退避状态也可能无法保存，会在 last_report 明示，不可能保证物理存储故障期间的新消息可靠落盘。
- 如果同时启动多个实例，旧实例会报并发版本冲突。必须由接入层重开并串行处理。
- 事实修订历史和永久印象仍可能积累，需要按实际存储量管理；本项目不承诺无限容量。
- 所有持久化文件均未加密。整理时原文和部分已有记忆会发送给配置的模型服务。
- 这是原型升级，不是与所有智能体框架或模型的兼容认证。
