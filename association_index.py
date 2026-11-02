"""Disposable event -> cue -> event index. Never stores event prose or facts."""
from collections import defaultdict
import math


class AssociationIndex:
    """Rebuilt from eligible ledger entries each read; no deletion synchronization."""
    def __init__(self, nodes, now, *, half_life_days=90, fanout=20):
        self.nodes, self.now = nodes, now
        self.half_life = half_life_days * 86400
        self.fanout = fanout
        self.by_cue = defaultdict(list)
        self.cues = {}
        for mid, m in nodes.items():
            # Only explicit structured cues; no automatic all-bigram graph.
            cues = sorted({s.strip().casefold() for s in
                           m.get('keywords', []) + m.get('anchors', [])
                           if isinstance(s, str) and 2 <= len(s.strip()) <= 40})[:32]
            self.cues[mid] = cues
            for cue in cues:
                self.by_cue[cue].append(mid)
        for cue, ids in self.by_cue.items():
            ids.sort(key=lambda mid: (-nodes[mid]['created'], mid))

    def neighbors(self, mid):
        found = {}
        for cue in self.cues.get(mid, []):
            ids = self.by_cue[cue]
            # Ubiquitous cues are weak; each cue visits only bounded recent peers.
            specificity = 1 / math.sqrt(max(1, len(ids) - 1))
            for other in ids[:self.fanout + 1]:
                if other == mid:
                    continue
                age = max(0, self.now - min(self.nodes[mid]['created'],
                                           self.nodes[other]['created']))
                weight = .7 * specificity * 2 ** (-age / self.half_life)
                if weight > found.get(other, (0, ''))[0]:
                    found[other] = (weight, cue)
        return sorted(((other, weight, cue) for other, (weight, cue) in found.items()),
                      key=lambda x: (-x[1], x[0]))[:self.fanout]
