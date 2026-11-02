"""Integration contract only. No API SDK, DSH changes, or network calls."""
from yuyi_emotion import EmotionStore, AffectAdapter


def prepare_affect(*, emotion_db, assistant_id, now, evaluator=None,
                   new_event_context=None, source=None):
    """Caller invokes only for its own user/assistant pair.

    source IDs/timestamp/provenance come from the real host, not the evaluator.
    Existing memory scheduler, chat storage and messages remain host-owned.
    """
    store = EmotionStore(emotion_db, assistant_id=assistant_id)
    affect = AffectAdapter(store)
    decision = None
    if evaluator is not None and new_event_context is not None:
        if not isinstance(source, dict):
            raise ValueError('A meaningful new event needs host-owned source metadata')
        decision = affect.consider(evaluator, context=new_event_context, **source)
    packet = affect.reference(now)
    # Put only packet['text'] in a separate replaceable reference-data message.
    # Do not put complete numeric state/audit/config in the prompt, and do not
    # append old reference snapshots permanently to chat history.
    return {'emotion_reference': packet['text'], 'decision': decision,
            'observer_state': packet['state'], 'degraded': packet['degraded']}


# source example:
# {'event_id':'chat-123:event-9', 'evidence_id':'actual-message-9',
#  'session_id':'chat-123', 'timestamp':unix_seconds,
#  'evidence_kind':'user_message', 'verified':False}
# evaluator must implement evaluator(prompt)->strict JSON text.
# When no new event occurred, omit evaluator/new_event_context: only elapsed-time
# state is read, no model evaluation cost and no automatic emotion reinforcement.
