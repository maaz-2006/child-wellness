"""
The permission gate.

This is the single authority on "may this person see/touch this data about this
child". Every view, template and API response goes through it. It is
deliberately declarative: the rules are data (MATRIX), not scattered `if
request.user.role == ...` branches, which means

  * adding a role or a field is a one-line change,
  * the matrix rendered in the UI is generated from the code that actually
    enforces it, so the documentation cannot drift,
  * it is exhaustively testable (see core/tests/test_permissions.py).

Model: relationship (why this user is connected to this child) x resource
(what kind of data) -> access level. The role alone is never sufficient.

FAIL CLOSED: anything not explicitly granted is denied, and sensitive denials
are audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from django.core.exceptions import PermissionDenied

from .models import Role


class Access(IntEnum):
    """Ordered so `granted >= required` is a valid check."""

    NONE = 0
    AGGREGATE = 1  # counts / anonymised rollups only
    SUMMARY = 2  # derived values (scores, trends), not raw entries
    READ = 3  # individual records
    WRITE = 4  # create / update records
    MANAGE = 5  # full control including configuration and consent


class Resource:
    PROFILE = "profile"
    EMOTIONAL = "emotional"
    #: What an adult records *about* a child's emotional state.
    #:
    #: This is deliberately a different resource from EMOTIONAL. A mentor needs
    #: to be able to write "seemed withdrawn at break time" without thereby
    #: gaining the right to read the child's own private check-ins. Collapsing
    #: the two into one WRITE grant is the mistake that makes "the teacher can
    #: see your diary" possible, so the matrix keeps them apart.
    EMOTIONAL_OBSERVATION = "emotional_observation"
    ACADEMIC = "academic"
    SOCIAL = "social"
    HABITS = "habits"
    SCORE = "score"
    ALERT = "alert"
    CASE_NOTE = "case_note"
    MESSAGE = "message"
    CONSENT = "consent"
    FEEDBACK = "feedback"
    CONFIG = "config"
    AUDIT = "audit"


class Relation:
    OWN = "own"  # guardian of this specific child
    ASSIGNED = "assigned"  # mentor currently assigned to this specific child
    SELF = "self"  # the child themselves
    INSTITUTION = "institution"  # administrator: no direct relationship
    NONE = "none"


# ---------------------------------------------------------------------------
# The matrix. Read this as the requirements specification.
# ---------------------------------------------------------------------------
MATRIX: dict[tuple[str, str], dict[str, Access]] = {
    # ---- Parent / guardian of the child ----------------------------------
    (Role.PARENT, Relation.OWN): {
        Resource.PROFILE: Access.READ,
        Resource.EMOTIONAL: Access.READ,
        # A guardian observes their own child at home, so they can record an
        # observation. Writing an observation does not grant access to anyone
        # else's.
        Resource.EMOTIONAL_OBSERVATION: Access.WRITE,
        Resource.ACADEMIC: Access.READ,
        Resource.SOCIAL: Access.READ,
        # Sleep, screen time and breakfast are observed at home, so a guardian
        # logs them. WRITE does not widen reading: they already have READ on
        # this domain, and the row gate still hides other children's logs.
        Resource.HABITS: Access.WRITE,
        Resource.SCORE: Access.READ,
        # Parents see that a concern exists and what to do about it, but not
        # the mentor's internal case notes.
        Resource.ALERT: Access.SUMMARY,
        Resource.CASE_NOTE: Access.NONE,
        Resource.MESSAGE: Access.WRITE,
        Resource.CONSENT: Access.MANAGE,
        Resource.FEEDBACK: Access.WRITE,
        Resource.CONFIG: Access.NONE,
        Resource.AUDIT: Access.NONE,
    },
    # ---- Mentor currently assigned to the child --------------------------
    (Role.MENTOR, Relation.ASSIGNED): {
        Resource.PROFILE: Access.READ,
        # Emotional check-ins: trend and score, plus entries the child chose to
        # share. Never private free-text. Enforced again at queryset level.
        Resource.EMOTIONAL: Access.SUMMARY,
        Resource.EMOTIONAL_OBSERVATION: Access.WRITE,
        Resource.ACADEMIC: Access.WRITE,
        Resource.SOCIAL: Access.WRITE,
        Resource.HABITS: Access.WRITE,
        Resource.SCORE: Access.READ,
        Resource.ALERT: Access.WRITE,
        Resource.CASE_NOTE: Access.WRITE,
        Resource.MESSAGE: Access.WRITE,
        Resource.CONSENT: Access.NONE,
        Resource.FEEDBACK: Access.WRITE,
        Resource.CONFIG: Access.NONE,
        Resource.AUDIT: Access.NONE,
    },
    # ---- The child themselves --------------------------------------------
    # Note the two deliberate NONE rows: a child never sees their own risk
    # score, tier or any alert about them. Labelling a child as "at risk" in
    # their own interface is a harm vector, not a feature.
    (Role.CHILD, Relation.SELF): {
        Resource.PROFILE: Access.READ,
        Resource.EMOTIONAL: Access.WRITE,
        Resource.EMOTIONAL_OBSERVATION: Access.NONE,
        Resource.ACADEMIC: Access.SUMMARY,
        Resource.SOCIAL: Access.SUMMARY,
        Resource.HABITS: Access.WRITE,
        Resource.SCORE: Access.NONE,
        Resource.ALERT: Access.NONE,
        Resource.CASE_NOTE: Access.NONE,
        Resource.MESSAGE: Access.WRITE,
        Resource.CONSENT: Access.SUMMARY,
        Resource.FEEDBACK: Access.WRITE,
        Resource.CONFIG: Access.NONE,
        Resource.AUDIT: Access.NONE,
    },
    # ---- Administrator: institution-wide, aggregate only -----------------
    # Admins can create and maintain records, but cannot read emotional
    # content or case notes. "The person who can see everything" is a privacy
    # anti-pattern, not a convenience.
    (Role.ADMIN, Relation.INSTITUTION): {
        Resource.PROFILE: Access.MANAGE,
        Resource.EMOTIONAL: Access.NONE,
        Resource.EMOTIONAL_OBSERVATION: Access.NONE,
        Resource.ACADEMIC: Access.AGGREGATE,
        Resource.SOCIAL: Access.AGGREGATE,
        Resource.HABITS: Access.AGGREGATE,
        Resource.SCORE: Access.AGGREGATE,
        Resource.ALERT: Access.AGGREGATE,
        Resource.CASE_NOTE: Access.NONE,
        Resource.MESSAGE: Access.NONE,
        Resource.CONSENT: Access.MANAGE,
        Resource.FEEDBACK: Access.AGGREGATE,
        Resource.CONFIG: Access.MANAGE,
        Resource.AUDIT: Access.READ,
    },
}

#: Denials worth recording. Reading a mood log without permission is a
#: different event from a 404 on a missing page.
AUDITED_RESOURCES = {
    Resource.PROFILE,
    Resource.EMOTIONAL,
    Resource.EMOTIONAL_OBSERVATION,
    Resource.ACADEMIC,
    Resource.SOCIAL,
    Resource.HABITS,
    Resource.SCORE,
    Resource.CASE_NOTE,
    Resource.AUDIT,
}

RELATION_LABELS = {
    Relation.OWN: "Own child",
    Relation.ASSIGNED: "Assigned child",
    Relation.SELF: "Self",
    Relation.INSTITUTION: "Institution-wide",
    Relation.NONE: "No relationship",
}


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def is_authenticated(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def resolve_relation(user, child) -> str:
    """Why, if at all, does `user` have a relationship to `child`?

    Every branch requires an *active* link. Suspending a mentorship or revoking
    consent removes access immediately, without deleting history.
    """
    if not is_authenticated(user) or child is None:
        return Relation.NONE

    if user.role == Role.ADMIN:
        return Relation.INSTITUTION

    if user.role == Role.CHILD:
        profile = getattr(user, "child_profile", None)
        if profile is not None and profile.pk == child.pk:
            return Relation.SELF
        return Relation.NONE

    if user.role == Role.PARENT:
        from children.models import Guardianship

        linked = Guardianship.objects.filter(
            parent=user,
            child=child,
            is_active=True,
            consent_granted_at__isnull=False,
        ).exists()
        return Relation.OWN if linked else Relation.NONE

    if user.role == Role.MENTOR:
        from children.models import Mentorship

        linked = Mentorship.objects.filter(
            mentor=user,
            child=child,
            is_active=True,
        ).exists()
        return Relation.ASSIGNED if linked else Relation.NONE

    return Relation.NONE


def access_for(user, child, resource: str) -> Access:
    """Concrete access level for this user/child/resource triple."""
    if not is_authenticated(user):
        return Access.NONE
    relation = resolve_relation(user, child)
    return MATRIX.get((user.role, relation), {}).get(resource, Access.NONE)


def has_access(user, child, resource: str, required: Access = Access.READ) -> bool:
    return access_for(user, child, resource) >= required


def access_for_institution(user, resource: str) -> Access:
    """Access to institution-wide data that does not name a child.

    Some resources have an aggregate form that is not "a weaker view of one
    child" but a genuinely different thing: the average score of a cohort, a
    count of open alerts. Asking `access_for` for one of those is meaningless
    because there is no child to resolve a relationship against, so the
    institutional relation is used directly.

    Only a role with an INSTITUTION row in the matrix can receive anything;
    everyone else fails closed.
    """
    if not is_authenticated(user):
        return Access.NONE
    return MATRIX.get((user.role, Relation.INSTITUTION), {}).get(resource, Access.NONE)


def visible_children(user):
    """Queryset of children this user may see at all. Used by list views."""
    from children.models import Child, Guardianship, Mentorship

    if not is_authenticated(user):
        return Child.objects.none()

    if user.role == Role.ADMIN:
        return Child.objects.all()

    if user.role == Role.CHILD:
        return Child.objects.filter(pk=getattr(getattr(user, "child_profile", None), "pk", None))

    if user.role == Role.PARENT:
        return Child.objects.filter(
            guardianships__parent=user,
            guardianships__is_active=True,
            guardianships__consent_granted_at__isnull=False,
        ).distinct()

    if user.role == Role.MENTOR:
        return Child.objects.filter(
            mentorships__mentor=user,
            mentorships__is_active=True,
        ).distinct()

    return Child.objects.none()


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
def require_access(request, child, resource: str, required: Access = Access.READ) -> None:
    """Raise PermissionDenied (and audit the denial) unless access is granted."""
    if has_access(request.user, child, resource, required):
        return

    if resource in AUDITED_RESOURCES:
        from .audit import record_request

        record_request(
            request,
            action="deny",
            resource_type=resource,
            child=child,
            metadata={
                "required": Access(required).name,
                "granted": Access(access_for(request.user, child, resource)).name,
                "relation": resolve_relation(request.user, child),
            },
        )
    raise PermissionDenied("You do not have access to this information.")


def require_role(request, *roles: str) -> None:
    if not is_authenticated(request.user) or request.user.role not in roles:
        raise PermissionDenied("This area is not available to your account.")


# ---------------------------------------------------------------------------
# Introspection, for the generated matrix page and for the report appendix
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MatrixRow:
    role: str
    relation: str
    resource: str
    access: Access


def matrix_rows() -> list[MatrixRow]:
    rows: list[MatrixRow] = []
    for (role, relation), grants in MATRIX.items():
        for resource in sorted(grants):
            rows.append(MatrixRow(role, relation, resource, grants[resource]))
    return rows


RESOURCE_LABELS = {
    Resource.PROFILE: "Profile",
    Resource.EMOTIONAL: "Emotional wellness",
    Resource.EMOTIONAL_OBSERVATION: "Emotional observations",
    Resource.ACADEMIC: "Academic progress",
    Resource.SOCIAL: "Social development",
    Resource.HABITS: "Healthy habits",
    Resource.SCORE: "Wellness score",
    Resource.ALERT: "Early-warning alerts",
    Resource.CASE_NOTE: "Case notes",
    Resource.MESSAGE: "Messages",
    Resource.CONSENT: "Consent",
    Resource.FEEDBACK: "Feedback",
    Resource.CONFIG: "Configuration",
    Resource.AUDIT: "Audit log",
}
