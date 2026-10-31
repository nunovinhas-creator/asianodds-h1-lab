"""Fail closed on unproven SportScore CORE_NAME competition identities.

The review captures labels, not independent cross-provider identities.
Equal labels (even country-qualified) cannot establish a competition binding.
Legacy exact and explicitly reviewed fixture matching remains independent.
"""


def anchors(review, competitions, now):
    """Quarantine label-only CORE locators pending an evidenced binding.

    No independently verified competition binding producer exists yet.
    Caller-supplied flags, country names or IDs cannot invent that evidence.
    Reactivation needs a separately reviewed implementation and authorization.
    """
    return {}
