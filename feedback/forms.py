"""The guardian pulse form.

Two ratings and an optional sentence. The comment is capped because a pulse is
not a case note; a guardian who needs to say more should be talking to the
mentor, and a 5,000-character textarea invites a message that nobody has time to
handle.
"""

from __future__ import annotations

from django import forms

from .models import PulseResponse


class PulseForm(forms.ModelForm):
    class Meta:
        model = PulseResponse
        fields = ["wellbeing", "support", "comment"]
        widgets = {
            "wellbeing": forms.RadioSelect,
            "support": forms.RadioSelect,
            "comment": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Anything you want the school to know? Optional.",
                    "maxlength": 600,
                }
            ),
        }
        labels = {
            "wellbeing": "How has your child seemed this week?",
            "support": "How supported do you feel by the school?",
            "comment": "Anything you want the school to know?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["support"].required = False
        self.fields["comment"].required = False
