"""Safeguarding screening.

This module exists to answer one narrow question: does a free-text note contain
language that a trained adult should look at *today*? It does not decide that a
child is being harmed, and it does not replace the school's safeguarding policy.
It creates an urgent alert owned by the designated lead so that a disclosure
written in a check-in note does not wait for a weekly review.

Three deliberate limits:

1. **The text is never stored with the alert.** The alert records the category
   that matched, the date and the entry it came from. The note stays in the
   domain table under that domain's permission rule. A safeguarding queue is not
   a second, less-protected copy of a child's diary.
2. **The text is never shown back to the person who wrote it as a "match".**
   Matching is word- and phrase-based; quoting the matched fragment would be
   misleading and would leak content into an alert.
3. **Every match is urgent.** A false positive costs a conversation. A missed
   disclosure costs considerably more. The queue is designed for a human to
   triage, including dismissing a false positive with a note.

The phrase lists are intentionally short and behavioural rather than clinical.
They are a safety net, not a classifier, and the report says so.
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from . import engine
from .models import Alert
from .rules import RULE_LABELS, Finding
#: Each category is a list of lowercase phrases. Matching is on normalised
#: whitespace, so "hurting  myself" matches "hurting myself".
CATEGORIES: dict[str, tuple[str, ...]] = {
    "self_harm": (
        "hurt myself",
        "hurting myself",
        "kill myself",
        "end my life",
        "want to die",
        "don't want to be here",
        "do not want to be here",
        "self harm",
        "self-harm",
        "cutting myself",
        "suicidal",
    ),
    "harm_from_others": (
        "hits me",
        "hit me",
        "beat me",
        "beats me",
        "hurts me",
        "scared of him",
        "scared of her",
        "afraid of him",
        "afraid of her",
        "threatened me",
        "bullied me",
        "bullies me",
        "someone is hurting me",
    ),
    "unsafe_home": (
        "no one at home",
        "nobody at home",
        "left alone",
        "locked out",
        "not safe at home",
        "unsafe at home",
        "drunk at home",
        "hit by my",
        "touched me",
        "made me touch",
    ),
    "neglect": (
        "nothing to eat",
        "no food at home",
        "haven't eaten",
        "have not eaten",
        "no one looks after me",
        "nobody looks after me",
        "sleeping outside",
    ),
}

CATEGORY_LABELS = {
    "self_harm": "self-harm or suicidal language",
    "harm_from_others": "language suggesting harm by another person",
    "unsafe_home": "language suggesting an unsafe home situation",
    "neglect": "language suggesting neglect",
}


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def categories_for(text: str) -> list[str]:
    """Which categories match this text, in a stable order."""
    normalised = _normalise(text)
    if not normalised:
        return []
    return [
        category
        for category, phrases in CATEGORIES.items()
        if any(phrase in normalised for phrase in phrases)
    ]


def screen_and_alert(
    child,
    text: str,
    *,
    actor=None,
    source_resource: str = "",
    entry_id: str | int = "",
    as_of: date | None = None,
) -> list[Alert]:
    """Screen one note and raise an urgent alert per matching category.

    Returns the alerts that were created or updated. The caller should not need
    to branch on the result: an empty list means nothing matched.
    """
    matches = categories_for(text)
    if not matches:
        return []

    as_of = as_of or timezone.localdate()
    alerts: list[Alert] = []
    for category in matches:
        finding = Finding(
            rule_key=f"safeguarding_signal:{category}",
            tier=Alert.Tier.URGENT,
            domain="",
            title=f"Possible {CATEGORY_LABELS[category]}",
            summary=(
                f"A note entered on {as_of:%d %b %Y} contained language "
                f"associated with {CATEGORY_LABELS[category]}. The note itself "
                "is deliberately not copied here. The designated safeguarding "
                "lead should review the original entry and follow the school's "
                "safeguarding procedure."
            ),
            evidence={
                "category": category,
                "category_label": CATEGORY_LABELS[category],
                "screened_on": str(as_of),
                "source_resource": source_resource,
                "entry_id": str(entry_id or ""),
                "rule_label": RULE_LABELS["safeguarding_signal"],
                "text_stored": False,
            },
        )
        alerts.append(engine.persist_finding(child, finding, as_of, actor=actor))
    return alerts


def screen_request(
    request,
    child,
    text: str,
    *,
    source_resource: str = "",
    entry_id: str | int = "",
):
    """Screen a submitted note, route anything urgent, and audit the screening.

    The audit row records that a screen happened and which categories matched, but
    never the text. That distinction matters: the audit log is readable by the
    administrator and must not become a shadow copy of a child's note.
    """
    from core.audit import record_request

    alerts = screen_and_alert(
        child,
        text,
        actor=getattr(request, "user", None),
        source_resource=source_resource,
        entry_id=entry_id,
    )
    if alerts:
        record_request(
            request,
            action="safeguarding",
            resource_type="alert",
            child=child,
            resource_id=str(entry_id or ""),
            metadata={
                "categories": [alert.evidence.get("category") for alert in alerts],
                "source_resource": source_resource,
                "alerts": len(alerts),
            },
        )
    return alerts

