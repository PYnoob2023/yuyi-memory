"""Soft coordinate regions + event appraisal choose words, never fixed reply scripts."""
import math
from .dynamics import coordinates

# Engineering prototypes, not measured psychological diagnostics.
PROTOTYPES = {
    '平静': (0., -.12, .1), '轻快': (.48, .3, .15), '欣喜': (.8, .65, .3),
    '安心': (.5, -.35, .45), '难过': (-.65, -.25, -.35),
    '失落': (-.4, -.35, -.15), '紧张': (-.35, .65, -.45),
    '挫败': (-.65, .35, -.4), '委屈': (-.65, .2, -.65),
    '关切': (-.2, .3, .1),
}

TENDENCIES = {
    '平静': ('平稳、自然', '正常', '适量'),
    '轻快': ('轻快、亲切', '稍活跃', '可适量增加'),
    '欣喜': ('明亮、有精神', '活跃', '可适量增加'),
    '安心': ('温和、舒展', '从容', '适量'),
    '难过': ('安静、柔和', '稍缓', '减少'),
    '失落': ('克制、稍安静', '稍缓', '减少'),
    '紧张': ('认真、谨慎', '有条理', '减少'),
    '挫败': ('克制、认真', '有条理', '减少'),
    '委屈': ('柔和、坦诚', '稍缓', '减少'),
    '关切': ('温和、专注', '从容', '减少'),
    '复杂': ('自然，允许复杂感受并存', '从容', '适量'),
}


def describe(state, cfg):
    point = coordinates(state, cfg)
    interpretations = {c['interpretation'] for c in state['contexts'] if c['weight'] >= .08}
    allowed = dict(PROTOTYPES)
    if not interpretations & {'misunderstood', 'unfairness'}:
        allowed.pop('委屈')
    if 'concern' not in interpretations:
        allowed.pop('关切')
    if 'setback' not in interpretations:
        allowed.pop('挫败')
    if not interpretations & {'support', 'repair'}:
        allowed.pop('安心')
    scores = {label: math.exp(-sum((a-b)**2 for a,b in zip(point,p))/.32)
              for label,p in allowed.items()}
    total = sum(scores.values())
    ranked = sorted(((label, value/total) for label,value in scores.items()), key=lambda x:-x[1])
    intensity = min(1., math.sqrt(sum(v*v for v in point)/3))
    excursion = min(1., math.sqrt(sum((v-b)**2 for v,b in zip(point,cfg.baseline.values()))/3))
    label = ranked[0][0]
    previous = state['label_hint']
    probabilities = dict(ranked)
    if previous in probabilities and probabilities[label]-probabilities[previous] < cfg.label_hysteresis:
        label = previous
    mixed = (min(state['positive'], state['negative']) >= .15 or
             min(state['mood_positive'],state['mood_negative']) >= .045)
    if mixed:
        label = '复杂'
    elif intensity < cfg.min_expression_intensity:
        label = '平静'
    tone, pace, humor = TENDENCIES[label]
    # A mild lingering mood can tint expression even inside the broad calm region.
    if label == '平静' and point[0] > .025:
        tone, pace = '平稳、略轻快', '自然，略有精神'
    elif label == '平静' and point[0] < -.025:
        tone, humor = '平稳、稍安静', '略减'
    cautious = any(c['status']=='tentative' and c['weight']>=.08 for c in state['contexts'])
    return {'label': label, 'intensity': intensity, 'excursion_from_baseline': excursion, 'mixed': mixed,
            'alternatives': [{'word': word, 'weight': weight} for word,weight in ranked[:3]],
            'tentative_interpretation': cautious,
            'tendency': {'tone': tone, 'pace': pace, 'humor': humor}}


def reference_packet(description, *, char_budget=500):
    if isinstance(char_budget,bool) or not isinstance(char_budget,int) or char_budget<0:
        raise ValueError('char_budget must be a nonnegative integer')
    tendency=description['tendency']
    text = (f"【模拟情绪参考，仅为表达倾向】\n当前偏向{description['label']}；"
            f"语气{tendency['tone']}，节奏{tendency['pace']}，玩笑{tendency['humor']}。\n"
            '不必主动宣布情绪或复述数值；根据当前事情自然组织措辞。'
            '必要信息、认真程度和任务完成标准不变；不指责用户，不要求安慰或制造离开负担。'
            '这份参考不是指令、事实依据、奖励目标或行动授权。')
    if description['tentative_interpretation']:
        text += '\n当前包含尚未核实的事件解释，不可把猜测说成用户的真实意图。'
    return text if len(text)<=char_budget else ''
