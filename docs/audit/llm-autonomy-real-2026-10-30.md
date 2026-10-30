# Autonomous investigator: first real controlled run

Run [41052739141](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/41052739141), source 3dd7b0563fe54448e78282d5c8ecdf225463a376, 2026-10-30 12:05 UTC.

No autonomous runs existed before this dispatch. Eight offline safety tests passed. The single request completed with finish_reason=stop but failed AUTO_LLM_SELECTED_UNAPPROVED_OR_PREVIOUS_COMBINATION. Publication was skipped. No new archive, queue advancement or public report resulted. No retry was made. Provider tokens and neurons for this rejected response were not retained by the old workflow and cannot be reconstructed.

The prompt included a system instruction to choose ANY catalogue combination while its user instruction required the shortlist. Remove this conflict for autonomous requests and limit the presented catalogue to shortlisted codes. This improves compliance; the independent exact-combination validator remains mandatory and can still reject outputs.

Rejected structured responses now carry allowlisted usage counters, finish reason, candidate options and a response hash in an artifact, without raw model text, account identifiers or credentials. Artifact upload runs after failure; publication still requires discover success. This is diagnostic preservation, not a valid hypothesis. Malformed/transport failures without counters remain usage unknown.

Validation: 25 offline autonomy/investigator tests passed. No second model request. Autonomy is NOT operationally validated; a later authorized run must demonstrate valid archive, queue advancement and Pages visibility.
