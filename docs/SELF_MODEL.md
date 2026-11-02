# 自我模型与最小反思

默认观察模式，库里没有预装人格或共同经历。可选初始 name/role 由宿主显式提供，模型不能将反思结果当作身份配置。推断范围限于 capability/limitation/habit，保留局部范围和可修正性。

## 来源与审阅

Evidence 登记发生时间、经历 ID、范围、亲历/读来/想象、来源类型及宿主核实标记。同 session_id+occurrence_id 只计一次；工具重试与重新复述不要伪装成独立经历。

只有已核实的亲历 verified_outcome/user_feedback 计入支持或有效反例。自己的自述、读取、读来故事和未核实内容只作背景。默认至少 3 个独立经历、24 小时跨度、无有效反例才可审阅；门槛不是人格或认识正确性的证明。

draft 经显式 review 可 active；反例或来源撤回使 active 待复核 disputed。新版本批准后旧版本 retired，可在重新核验后 restore。rejected 不因重复提案自动复活。审阅使用版本号避免覆盖新证据。

## 试运行

```sh
python -m yuyi_self --assistant assistant-1 init
python -m yuyi_self --assistant assistant-1 show
python -m yuyi_self --assistant assistant-1 report --out self-trial-report.md
```

在少量有意义的新经历后登记来源，让 reflection_model(prompt) 提出严格 JSON 候选。示例见 examples/self_model/host_observer.py。反思只能引用本次给出的已登记来源，不能核实自己编造的来源或批准候选。

记录者可在正常回顾时审阅，不要求用户每天打分。重点是依据、范围、反例与是否只是复述人设；不追求候选数量或成长速度。达到门槛但保留不确定也正常。

`store.reference(scope='debugging')` 默认空文本。只有显式 enabled=True 才返回当前证据仍合格、已批准且范围相同的少量参考，不生成系统指令或行动权限。

模块无法自动知道不同措辞是否表达同一认识、哪个新事件反驳哪条认识。模型与审阅仍可能错。标记 verified 只表示来源核实，不等于结论成立。操作者名字是审计字段，不是身份认证。

自我判断 statement 和 reason 是需要保存的自由文本，应避免包含不必要的私人细节。撤回是留痕回滚，不是物理删除。本版不改原有记忆、情绪基线或人设文件，不具备自动核心规则学习。
