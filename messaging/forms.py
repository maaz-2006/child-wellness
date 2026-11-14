"""Forms for starting a thread and adding a message.

Plain forms rather than ModelForms: the service layer owns creation and the
append-only rule, and a form that called `Message.save()` directly would be a
second write path to audit.
"""

from __future__ import annotations

from django import forms


class ThreadForm(forms.Form):
    subject = forms.CharField(
        max_length=160,
        label="Subject",
        widget=forms.TextInput(
            attrs={"placeholder": "What is this conversation about?"}
        ),
    )
    body = forms.CharField(
        label="First message",
        max_length=4000,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Write to the other adults who know this child.",
            }
        ),
    )


class MessageForm(forms.Form):
    body = forms.CharField(
        label="Message",
        max_length=4000,
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "Add a message to this conversation."}
        ),
    )
