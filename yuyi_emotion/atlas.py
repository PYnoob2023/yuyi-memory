"""Inspectable 3D emotion-word array; optional visualization/export surface."""
from .expression import PROTOTYPES
from .model import PAD

REQUIRES = {'委屈': ['misunderstood', 'unfairness'], '关切': ['concern'],
            '挫败': ['setback'], '安心': ['support', 'repair']}


class EmotionAtlas:
    """Sampled word-region candidates. Runtime state remains continuous.

    A cell supplies candidate words, never proof of a psychological state.
    Event-context gates in expression.describe still decide eligibility.
    """
    def __init__(self, resolution=9):
        if isinstance(resolution, bool) or not isinstance(resolution, int) or not 3 <= resolution <= 17:
            raise ValueError('resolution must be 3..17')
        self.resolution = resolution
        axis=[-1+2*i/(resolution-1) for i in range(resolution)]
        self.cells=tuple(tuple(tuple(self._cell(PAD(p,a,d)) for d in axis)
                               for a in axis) for p in axis)

    @staticmethod
    def _cell(point):
        ranked=sorted(PROTOTYPES, key=lambda word:sum((a-b)**2 for a,b in zip(point.values(),PROTOTYPES[word])))
        return tuple(ranked[:3])

    def locate(self, point):
        if not isinstance(point,PAD):
            raise ValueError('Expected PAD')
        indices=tuple(round((x+1)*(self.resolution-1)/2) for x in point.values())
        words=self.cells[indices[0]][indices[1]][indices[2]]
        return {'indices':list(indices),'candidates':[{'word':w,'requires_any':REQUIRES.get(w,[])} for w in words]}

    def export(self):
        return {'schema':'yuyi-emotion-atlas-1','axes':['pleasure','arousal','agency'],
                'range':[-1,1],'resolution':self.resolution,'cells':self.cells,
                'context_requirements':REQUIRES,
                'note':'Sampled candidates for visualization; runtime expression uses continuous distances and context.'}
