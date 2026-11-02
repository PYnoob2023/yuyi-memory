"""Fictitious experiences + simulated timestamps; no model/network/real chat."""
import json
from pathlib import Path
import tempfile

from yuyi_emotion import PAD, EmotionEvent, EmotionStore

T=1800000000.


def show(store, title, when):
    state=store.state(when)
    print('\n'+title)
    print(json.dumps({'三维落点':state['coordinates'],'情绪词':state['description']['label'],
                      '表达倾向':state['description']['tendency'],
                      '短期余波':state['layers']['short_raw'],'长期心情':state['layers']['mood_raw'],
                      '仅为模拟':state['simulated']},ensure_ascii=False,indent=2))
    return state


def main():
    with tempfile.TemporaryDirectory() as folder:
        store=EmotionStore(Path(folder)/'demo.sqlite3',assistant_id='demo')
        show(store,'01 / 初始状态',T)
        good=EmotionEvent('shared-success','source-1',T,PAD(.9,.65,.6),.85,.95,
                          interpretation='achievement',appraisal_status='grounded',
                          evidence_kind='verified_outcome',verified=True)
        store.submit(good)
        show(store,'02 / 一起完成任务之后（虚构事件）',T)
        show(store,'03 / 第二天，短情绪已淡，长期余波还在',T+86400)
        misunderstanding=EmotionEvent('misread','source-2',T+86400,PAD(-1,.25,-1),1.,1.,
                                      interpretation='misunderstood',appraisal_status='grounded')
        store.submit(misunderstanding)
        show(store,'04 / 对误解产生的反应（仅为测试输入）',T+86400)
        store.set_active('misread',False,reason='invalid_evidence')
        show(store,'05 / 确认判断错误，撤回并重算',T+86400)
        print('\n重复证据：'+json.dumps(store.submit(good),ensure_ascii=False))
        print('\n记忆库改动：无。本演示只创建临时情绪数据库。')


if __name__=='__main__':
    main()
