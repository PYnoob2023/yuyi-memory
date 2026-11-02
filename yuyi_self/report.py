"""Local, human-readable trial report. No send, upload or background scheduling."""
def trial_report(store):
    snap=store.snapshot()
    lines=['# 自我模型试运行观察报告','',f"助手：{snap['assistant_id']}",'默认模式：观察，不注入聊天、不改写人设。',
           f"来源记录：{snap['evidence_count']}；候选与历史版本：{len(snap['claims'])}",'',
           '| 范围 | 自我认识 | 状态 | 独立支持 | 跨度（小时） | 反例 |',
           '|---|---|---|---:|---:|---:|']
    def safe(s):return str(s).replace('|','／').replace('\n',' ')
    for c in snap['claims']:
        a=c['assessment'];lines.append(f"| {safe(c['scope'])} | {safe(c['statement'])} | {c['status']} | {a['support_count']} | {a['span_hours']:.1f} | {len(a['challenges'])} |")
    lines+=['','观察重点：','- 每条认识是否能追溯到真实经历，而非自己的反复自述？',
            '- 是否承认反例，避免一次事件变成人格定论？','- 相似事件是否被重复计数？',
            '- 这些认识是否有助于理解自己，还是只复述人设？','- 若选择启用参考，措辞是否自然、判断是否仍以当前证据为准？',
            '','达到门槛只表示可以审阅，不是人格形成或意识出现的证明。']
    return '\n'.join(lines)+'\n'
