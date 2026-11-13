"""Template context available on every page.

Kept tiny on purpose: this runs on every render. Expensive per-request work
(alert counts, trend data) belongs in the view or a cached helper.
"""

from django.conf import settings

from .models import Role


def platform(request):
    user = getattr(request, "user", None)
    return {
        "platform_name": getattr(settings, "PLATFORM_NAME", "Kito"),
        "platform_tagline": getattr(settings, "PLATFORM_TAGLINE", ""),
        "role_parent": Role.PARENT,
        "role_mentor": Role.MENTOR,
        "role_child": Role.CHILD,
        "role_admin": Role.ADMIN,
        "is_platform_admin": bool(
            getattr(user, "is_authenticated", False) and getattr(user, "role", None) == Role.ADMIN
        ),
    }
