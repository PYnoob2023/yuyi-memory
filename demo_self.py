"""Fictitious trial, temporary DB. Does not set up a real assistant or timer."""
from pathlib import Path
import tempfile
from yuyi_self import Evidence,Proposal,SelfModel,trial_report


def main():
    with tempfile.TemporaryDirectory() as folder:
        s=SelfModel(Path(folder)/'demo.sqlite3',assistant_id='fictional-demo')
        s.register(Evidence('a','case-a','demo',1700000000.,'debugging','verified_outcome',verified=True))
        p=Proposal('debugging.log_checks','habit','debugging','在排查代码问题时，我倾向先核实日志。',('a',))
        cid=s.propose(p,author='fictional-demo')
        print('一段经历：',s.claims()[0]['assessment'])
        for i,eid in enumerate(('b','c'),1):
            s.register(Evidence(eid,'case-'+eid,'demo',1700000000.+i*43200,'debugging','verified_outcome',verified=True))
        s.propose(Proposal(p.key,p.category,p.scope,p.statement,('a','b','c')),author='fictional-demo')
        current=next(c for c in s.claims() if c['id']==cid)
        s.review(cid,'approve',reviewer='fictional-self-review',expected_version=current['version'])
        print('已审阅，但默认仍不注入：',s.reference(scope='debugging'))
        print('显式启用相关范围参考：',s.reference(scope='debugging',enabled=True))
        s.register(Evidence('counter','case-counter','demo',1700200000.,'debugging','verified_outcome',verified=True))
        s.propose(Proposal(p.key,p.category,p.scope,p.statement,('a','b','c'),('counter',)),author='fictional-demo')
        print('出现反例后停止引用：',s.reference(scope='debugging',enabled=True))
        print(trial_report(s))


if __name__=='__main__':main()
