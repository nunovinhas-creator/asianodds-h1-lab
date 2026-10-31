"""Reuse explicit free-plan rejection of the plural IDs parameter only.

Does not infer absence, deny singular ID access or change request budgets.
"""
import re
from datetime import timedelta
from .lab_results import utc

_DENIAL = re.compile(r'free plans? do not have access to (?:the )?ids parameter', re.I)


def id_batch_policy(audit, now):
    proofs = []
    for run in audit.get('runs', []):
        provider = run.get('providers', {}).get('api_football', {})
        candidates = [(run.get('utc'), detail)
                      for detail in provider.get('id_errors', {}).values()]
        carried = provider.get('strict_index_probe', {}).get('id_parameter_policy')
        if isinstance(carried, dict):
            candidates.append((carried.get('checked_at_utc'), carried))
        for stamp, detail in candidates:
            checked = utc(stamp)
            if (checked is None or not timedelta(0) <= now-checked <= timedelta(days=45)
                    or not isinstance(detail, dict)
                    or (detail.get('category'), detail.get('http_status')) not in (
                        ('PROVIDER_ERRORS', 200), ('HTTP_ERROR', 400),
                        ('HTTP_ERROR', 403), ('HTTP_ERROR', 422))
                    or not isinstance(detail.get('provider_errors'), str)
                    or not _DENIAL.search(detail['provider_errors'])):
                continue
            proofs.append({'scope': 'IDS_PARAMETER_ONLY',
                'checked_at_utc': checked.isoformat(timespec='seconds'),
                'category': detail['category'], 'http_status': detail['http_status'],
                'provider_errors': detail['provider_errors'][:200],
                'singular_id_access': 'NOT_PROVEN'})
    return (1, max(proofs, key=lambda p:p['checked_at_utc'])) if proofs else (20, None)
