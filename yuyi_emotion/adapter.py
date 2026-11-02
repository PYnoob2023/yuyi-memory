"""Opt-in host boundary. No model SDK, sends, background jobs, or memory imports."""
from .assessor import assess


class AffectAdapter:
    def __init__(self, store):
        self.store = store

    def consider(self, model, **event_context):
        """Call only for a proposed meaningful new event, not on every status read."""
        try:
            event = assess(model, **event_context)
            return self.store.submit(event)
        except Exception as error:
            # No fabricated fallback emotion; host can continue its normal answer.
            return {'accepted': False, 'reason': 'assessment_unavailable', 'error_type': type(error).__name__}

    def reference(self, timestamp, *, char_budget=500):
        try:
            state = self.store.state(timestamp, char_budget=char_budget)
            return {'text': state['reference'], 'state': state, 'degraded': False}
        except Exception as error:
            return {'text': '', 'state': None, 'degraded': True, 'error_type': type(error).__name__}
