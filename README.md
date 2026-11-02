# 余忆 · Yuyi

为对话助手提供可检查、可更正、可迁移的外部状态：**记忆保存经历，情绪留下余波，自我模型记录有依据的认识。** 神经观察舱把事件、线索和召回路径呈现在可交互网络中。

这是模型之外的实验性 Python 项目，不修改模型权重，不证明 AI 拥有意识或真实情感。模块默认独立：**情绪尚不调整记忆寿命或召回权重，自我模型默认只观察，不注入聊天。**

[English](README.en.md) · [项目说明](docs/PROJECT.md) · [宿主接入](docs/INTEGRATION.md) · [隐私边界](docs/PRIVACY.md) · [MIT License](LICENSE)

## 快速运行

Python 3.10+，运行时仅用标准库。下载完整仓库，在根目录执行：

```sh
python demo_reading.py
python demo_emotion.py
python demo_self.py
python -m unittest discover -v
```

演示使用虚构内容和临时数据库，不调用真实模型。可直接从源码运行；也可选择 `python -m pip install .` 安装 Python 模块及命令行入口。安装构建工具可能需要联网，运行模块无需第三方依赖。

在默认西文编码的 Windows 终端运行中文演示/测试时，使用 `python -X utf8 ...`，例如 `python -X utf8 -m unittest discover -v`。两个新命令行入口会自行将标准输出设为 UTF-8，库导入不会改宿主的编码设置。

## 四个部分

| 部分 | 当前能力 | 说明 |
|---|---|---|
| 记忆 | SQLite 账本、来源检查、分层遗忘、项目调度、关键词关联、路径审计 | [记忆](docs/MEMORY.md) |
| 情绪 | 常态/长期/短期状态、三维落点、语境判词、表达参考、撤回重算 | [情绪](docs/EMOTION.md) |
| 自我模型 | 能力/局限/习惯候选、独立来源、反例、审阅、版本历史 | [自我模型](docs/SELF_MODEL.md) |
| 观察舱 | 可旋转神经场、激活脉冲、事件观察、账本导入导出、本地接口 | [观察舱](docs/VIEWER.md) |

## 记忆：存得准确，有依据地想起

```python
from companion_memory import CompanionMemory
from project_memory import ProjectMemory
from turn_reader import ChatMemory as TurnReader

memory = CompanionMemory('data/user-1/assistant-1/memory', user_title='朋友')
projects = ProjectMemory('data/user-1/assistant-1/projects', memory,
                         identity='如实回答，不编造共同经历。', session='chat-1')
reader = TurnReader(projects, system_prompt='你是一个认真倾听的助手。')

# 可信宿主确认的虚构示例，不要让模型任意调用写入或确认接口。
memory.remember('蓝桥公司加班后在河边谈过项目', anchors=['蓝桥'])
memory.remember('蓝桥旧约定是晚上十一点休息', anchors=['蓝桥'])
messages, packet = reader.prepare('又在加班')
print(packet.text)
print(packet.recall_audit)
```

中文检索使用连续中文段的二字组合，英文和数字使用完整片段，避免 `hello` 的碎片误撞 `scheduler`。关联索引可重建，只补充候选和排序；正文来自账本。新读取入口不使用无关近期事件补位，也不自动巩固。

旧 `CompanionMemory.build_context/retrieve` 保留兼容行为，新接入优先使用 `ProjectMemory + TurnReader`。不要重复注入快照或重复记录同一轮消息。

## 情绪：跨轮次保留有界余波

```sh
python -m yuyi_emotion --db data/emotion.sqlite3 init
python -m yuyi_emotion --db data/emotion.sqlite3 status
```

宿主模型提出结构化事件解释，代码检查并维护三层状态。三维坐标结合语境形成情绪词和措辞倾向，不要求模型背台词、宣布数值或降低任务完成标准。查看状态不写库、不强化；不因用户离线生成被抛弃事件。

## 自我模型：先观察，再决定采用什么

```sh
python -m yuyi_self --assistant assistant-1 init
python -m yuyi_self --assistant assistant-1 report --out self-trial-report.md
```

真实经历产生局部候选。默认需要三个独立、核实过的经历、至少 24 小时跨度且无有效反例，才具备审阅条件；这不是人格形成的证明。批准后默认仍只观察。反思模型不能自行登记已核实来源、批准认识或修改身份。

## 神经记忆观察舱

```sh
python viewer/serve_neural.py
```

打开 `http://127.0.0.1:8765`。首次在 `viewer/runtime_data/` 创建独立演示库。先复制自己的账本，再使用 `--data /path/to/memory-copy` 查看；界面可写，写入、压制、删除会修改该目录。不要同时运行多个写入实例。

直接打开 `viewer/dist/index.html` 则使用独立的浏览器本地演示。装饰神经元用于视觉表现，实际事件和召回路径来自当前数据，不是生物脑扫描。

## 接入现有助手

项目不包含 QQ/DSH 登录、消息发送、模型 SDK、后台任务或 API 密钥。宿主需要提供实际来源编号、核验、模型评估回调与原有聊天循环。参考文本放在独立、可替换、低权限的数据消息中。详见 [接入说明](docs/INTEGRATION.md)。

每对用户与助手使用不同目录。情绪与自我认识不是事实证据或执行权限。各模块可以分别使用；安装后不会自动影响聊天。

## 验证与限制

项目包含离线回归、命令行端到端和本地 HTTP API 测试，并配置 Linux/Windows CI。测试验证规则和接口，不代表真实模型语义理解、表达自然度或真实宿主集成已验证。

关键词检索不能自动解决同义词、指代、否定、讽刺与跨语言，单字中文查询仍可能为空。情绪评估和自我反思都可能误判。当前没有加密、账户系统、生产级归档或掉电恢复验证。

仓库仅包含通用代码和虚构示例，不包含私人聊天、真实账本、Cookie、密钥、个人启动脚本或已部署站点身份。公开代码采用 [MIT](LICENSE)。
