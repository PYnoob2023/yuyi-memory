"""Host integration contract. No network, old-module import, persona editing or timer."""
from yuyi_self import Evidence,SelfModel,SelfAdapter,trial_report


def observe_experience(*,db,assistant_id,source,context,reflection_model,author):
    """Host supplies actual source metadata; the reflection model cannot verify it.

    source has Evidence's fields. Group tool calls/retries/retellings of the same
    experience under the same session_id+occurrence_id.
    context is transient and should be limited to this meaningful experience.
    """
    store=SelfModel(db,assistant_id=assistant_id)
    registered=store.register(Evidence(**source))
    if not registered['accepted']:
        return {'skipped':'already observed','canonical_id':registered['canonical_id']}
    result=SelfAdapter(store).observe(reflection_model,context=context,
                                    source_ids=[registered['canonical_id']],author=author)
    return {'reflection':result,'report':trial_report(store),'prompt_injected':False}


# To compare with earlier observations, the host can deliberately provide several
# registered source IDs to SelfAdapter.observe. No read/write of memory or emotion
# databases is necessary. A failed reflection leaves the registered evidence;
# retry it directly with that ID rather than inventing another occurrence.
# Candidates are reviewed with SelfModel.review after inspecting the sources.
# Even approved candidates remain out of chat unless reference(enabled=True,...)
# is explicitly requested by the host. Default trial only produces reports.
