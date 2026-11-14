"""Messaging is deliberately absent from the Django admin.

The platform's administrator role has `MESSAGE: NONE` in the permission matrix.
Registering these models would create a second surface where the same role could
read family correspondence, which would make the matrix a decoration. Messages
are read in the application by the adults who have a relationship to the child.
"""
