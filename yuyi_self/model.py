"""Evidence contracts for a provisional self model, not a claim of consciousness."""
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import re


def text(value,name,limit=160):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):
        raise ValueError(f'{name}: nonempty single-line text, max {limit}')
    return value


def timestamp(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError('Expected finite nonnegative Unix seconds')
    return value


@dataclass(frozen=True)
class Config:
    min_experiences: int = 3
    min_span_hours: float = 24.

    def __post_init__(self):
        if isinstance(self.min_experiences,bool) or not isinstance(self.min_experiences,int) or not 2<=self.min_experiences<=20:
            raise ValueError('min_experiences must be 2..20')
        timestamp(self.min_span_hours)
        if not 1<=self.min_span_hours<=8760: raise ValueError('min_span_hours must be 1..8760')

    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Evidence:
    id: str
    occurrence_id: str
    session_id: str
    occurred_at: float
    scope: str
    kind: str
    origin: str = 'experienced'
    verified: bool = False

    def __post_init__(self):
        for key in ('id','occurrence_id','session_id','scope'):text(getattr(self,key),key)
        timestamp(self.occurred_at)
        if self.kind not in ('verified_outcome','user_feedback','self_report','retrieval'):
            raise ValueError('Unknown evidence kind')
        if self.origin not in ('experienced','read_about','imagined') or not isinstance(self.verified,bool):
            raise ValueError('Invalid origin/verified')

    def occurrence_key(self):
        return hashlib.sha256(json.dumps([self.session_id,self.occurrence_id]).encode()).hexdigest()


@dataclass(frozen=True)
class Proposal:
    key: str
    category: str
    scope: str
    statement: str
    support_ids: tuple = ()
    challenge_ids: tuple = ()

    def __post_init__(self):
        text(self.key,'key',100);text(self.scope,'scope',100);text(self.statement,'statement',300)
        if not re.fullmatch(r'[a-z][a-z0-9_.-]*',self.key):raise ValueError('key must be stable lowercase ASCII')
        if self.category not in ('capability','limitation','habit'):
            raise ValueError('Only capability/limitation/habit; identity and rules are not inferred')
        if self.scope.lower() in ('global','all','everything','全部','所有'):
            raise ValueError('Use a concrete scope instead of a global personality judgment')
        for ids in (self.support_ids,self.challenge_ids):
            if not isinstance(ids,(list,tuple)) or len(ids)>30 or len(set(ids))!=len(ids):raise ValueError('Invalid evidence IDs')
            for value in ids:text(value,'evidence ID')
        if not self.support_ids or set(self.support_ids)&set(self.challenge_ids):
            raise ValueError('Need support; one source cannot support and challenge the same statement')
