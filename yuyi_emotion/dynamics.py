"""Deterministic three-layer state; no clock, storage, model calls or memory writes."""
import math
from copy import deepcopy


def initial():
    return {'time': None, 'short': [0., 0., 0.], 'mood': [0., 0., 0.],
            'positive': 0., 'negative': 0., 'mood_positive': 0., 'mood_negative': 0.,
            'contexts': [], 'label_hint': '平静'}


def advance(state, timestamp, cfg):
    if state['time'] is None:
        state['time'] = timestamp
        return
    if timestamp < state['time']:
        raise ValueError('Out-of-order time; use a separate sorted historical replay')
    dt = timestamp-state['time']
    for key, hours in [('short', cfg.short_half_life_hours), ('mood', cfg.mood_half_life_hours)]:
        factor = 2**(-dt/(hours*3600))
        state[key] = [v*factor for v in state[key]]
    short_factor = 2**(-dt/(cfg.short_half_life_hours*3600))
    state['positive'] *= short_factor
    state['negative'] *= short_factor
    mood_factor = 2**(-dt/(cfg.mood_half_life_hours*3600))
    state['mood_positive'] *= mood_factor
    state['mood_negative'] *= mood_factor
    for item in state['contexts']:
        item['weight'] *= short_factor
    state['contexts'] = [c for c in state['contexts'] if c['weight'] >= .015][-32:]
    state['time'] = timestamp


def apply(state, event, cfg):
    advance(state, event.timestamp, cfg)
    strength = event.intensity*event.confidence
    # A tentative interpretation can leave a small immediate ripple, never a long mood.
    short_weight = strength*(1 if event.appraisal_status == 'grounded' else .35)
    mood_weight = strength if event.appraisal_status == 'grounded' else 0.
    for key, gain, weight in [('short', cfg.short_gain, short_weight), ('mood', cfg.mood_gain, mood_weight)]:
        state[key] = [max(-cfg.max_raw_load, min(cfg.max_raw_load, x+gain*weight*d))
                      for x, d in zip(state[key], event.impact.values())]
    load = abs(event.impact.pleasure)*short_weight
    key = 'positive' if event.impact.pleasure >= 0 else 'negative'
    state[key] = min(cfg.max_raw_load, state[key]+load)
    mood_key = 'mood_positive' if event.impact.pleasure >= 0 else 'mood_negative'
    state[mood_key] = min(cfg.max_raw_load,state[mood_key]+abs(event.impact.pleasure)*mood_weight*cfg.mood_gain)
    state['contexts'].append({'event_id': event.event_id, 'interpretation': event.interpretation,
                              'status': event.appraisal_status, 'weight': short_weight})
    state['contexts'] = state['contexts'][-32:]


def coordinates(state, cfg):
    return [math.tanh(math.atanh(base)+short+long)
            for base, short, long in zip(cfg.baseline.values(), state['short'], state['mood'])]


def future(state, timestamp, cfg):
    result = deepcopy(state)
    advance(result, timestamp, cfg)
    return result
