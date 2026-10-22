"""Optional read-only tool. Instantiate one MemoryTools per assistant reply."""
import json

RECALL_TOOL = {
    'name': 'recall_memory',
    'description': '按线索查找真实保存的往事；只能返回仍可记起的内容，不能恢复已删除细节。',
    'parameters': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'maxLength': 500},
        'char_budget': {'type': 'integer', 'minimum': 1, 'maximum': 1200}},
        'required': ['query'], 'additionalProperties': False},
}


class MemoryTools:
    def __init__(self, memory, max_calls=2):
        if not isinstance(max_calls, int) or max_calls < 1:
            raise ValueError('max_calls must be positive')
        self.memory, self.max_calls, self.calls = memory, max_calls, 0

    def run(self, name, arguments):
        if name != 'recall_memory':
            raise ValueError('Unknown or unauthorized tool')
        if self.calls >= self.max_calls:
            return {'error': 'recall_call_limit'}
        if not isinstance(arguments, dict) or set(arguments) - {'query', 'char_budget'}:
            raise ValueError('Invalid arguments')
        query, budget = arguments.get('query'), arguments.get('char_budget', 400)
        if not isinstance(query, str) or len(query) > 500:
            raise ValueError('query must be a string of at most 500 characters')
        if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 1200:
            raise ValueError('Invalid character budget')
        self.calls += 1
        results = []
        limit = min(budget, int(self.memory.cfg['context_char_budget']))
        for memory in self.memory.retrieve(query):
            entry = {'id': memory['id'], 'stage': memory['stage'],
                     'kind': memory.get('kind', 'event'),
                     'status': memory.get('status', 'recorded'),
                     'content': self.memory._render(memory)}
            candidate = {'results': results + [entry]}
            # Budget includes the serialized envelope, not just text strings.
            if len(json.dumps(candidate, ensure_ascii=False)) <= limit:
                results.append(entry)
        return {'results': results}
