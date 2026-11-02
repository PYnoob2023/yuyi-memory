"""Validated, text-free inputs for a simulated affect state. Python 3.10+."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

INTERPRETATIONS = {'neutral', 'support', 'achievement', 'repair', 'misunderstood',
                   'unfairness', 'loss', 'threat', 'setback', 'concern', 'uncertain'}
EVIDENCE_KINDS = {'user_message', 'verified_outcome', 'agent_reflection',
                  'recalled_memory', 'unknown'}


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite in [{low}, {high}]')
    return float(value)


def identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 160 or any(ord(c) < 32 for c in value):
        raise ValueError(f'{name} must be a nonempty opaque ID, max 160 characters')
    return value


@dataclass(frozen=True)
class PAD:
    pleasure: float = 0.0
    arousal: float = 0.0
    agency: float = 0.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            number(value, name, -1, 1)

    def values(self):
        return [self.pleasure, self.arousal, self.agency]


@dataclass(frozen=True)
class Config:
    baseline: PAD = PAD()
    short_half_life_hours: float = 2.0
    mood_half_life_hours: float = 72.0
    short_gain: float = 0.9
    mood_gain: float = 0.12
    confidence_threshold: float = 0.75
    label_hysteresis: float = 0.08
    max_raw_load: float = 3.0
    min_expression_intensity: float = 0.06

    def __post_init__(self):
        if not isinstance(self.baseline, PAD):
            raise ValueError('baseline must be PAD')
        for value in self.baseline.values():
            number(value, 'baseline axis', -.9, .9)
        for name in ('short_half_life_hours', 'mood_half_life_hours'):
            number(getattr(self, name), name, .01, 24*365)
        if self.mood_half_life_hours <= self.short_half_life_hours:
            raise ValueError('mood must decay more slowly than short affect')
        for name in ('short_gain', 'mood_gain'):
            number(getattr(self, name), name, 0, 1)
        for name in ('confidence_threshold', 'min_expression_intensity'):
            number(getattr(self, name), name, 0, 1)
        number(self.label_hysteresis, 'label_hysteresis', 0, .5)
        number(self.max_raw_load, 'max_raw_load', .5, 5)

    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if 'baseline' in data:
            data['baseline'] = PAD(**data['baseline'])
        return cls(**data)


@dataclass(frozen=True)
class EmotionEvent:
    event_id: str
    evidence_id: str
    timestamp: float
    impact: PAD
    intensity: float
    confidence: float
    session_id: str = 'default'
    owner: str = 'self'
    evidence_kind: str = 'user_message'
    interpretation: str = 'neutral'
    appraisal_status: str = 'tentative'
    verified: bool = False

    def __post_init__(self):
        for name in ('event_id', 'evidence_id', 'session_id'):
            identifier(getattr(self, name), name)
        number(self.timestamp, 'timestamp (Unix seconds)', 0, 10**12)
        if not isinstance(self.impact, PAD):
            raise ValueError('impact must be PAD')
        number(self.intensity, 'intensity', 0, 1)
        number(self.confidence, 'confidence', 0, 1)
        if self.owner not in ('self', 'user', 'other'):
            raise ValueError('Invalid emotion owner')
        if self.evidence_kind not in EVIDENCE_KINDS or self.interpretation not in INTERPRETATIONS:
            raise ValueError('Unknown evidence kind or interpretation')
        if self.appraisal_status not in ('grounded', 'tentative') or not isinstance(self.verified, bool):
            raise ValueError('Invalid appraisal status or verified flag')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['impact'] = PAD(**data['impact'])
        return cls(**data)

    def evidence_key(self):
        return hashlib.sha256(json.dumps([self.session_id, self.evidence_id], ensure_ascii=False).encode()).hexdigest()
