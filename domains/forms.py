"""Forms for entering wellness data.

Two audiences, two forms, deliberately different.

The child form is short and concrete: five-point scales with faces, one optional
note, and a plain-language choice about who can read that note. A nine-year-old
should be able to finish it in under a minute and should never be asked to
understand the word "visibility".

The adult form is a professional record. It can be back-dated, it separates the
structured rating from the free-text note, and it makes the note's audience
explicit at the point of writing - because "who will read this" is the question
staff get wrong most often.
"""

from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import EmotionalCheckin, NoteVisibility, Source

#: Emoji carry the meaning faster than the words do, for both audiences.
MOOD_CHOICES = [
    (1, "😞 Struggling"),
    (2, "🙁 Low"),
    (3, "😐 Okay"),
    (4, "🙂 Good"),
    (5, "😄 Great"),
]
ENERGY_CHOICES = [
    (1, "🪫 Exhausted"),
    (2, "😴 Tired"),
    (3, "😐 Fine"),
    (4, "⚡ Energetic"),
    (5, "🚀 Full of energy"),
]
QUALITY_CHOICES = [
    (1, "Very poor"),
    (2, "Poor"),
    (3, "Okay"),
    (4, "Good"),
    (5, "Very good"),
]
CONNECTION_CHOICES = [
    (1, "Very alone"),
    (2, "A bit alone"),
    (3, "Okay"),
    (4, "Connected"),
    (5, "Very connected"),
]

CHILD_NOTE_CHOICES = [
    (NoteVisibility.PRIVATE, "Just me"),
    (NoteVisibility.MENTOR, "Me and my mentor"),
    (NoteVisibility.ALL, "Me, my mentor and my grown-up"),
]

ADULT_NOTE_CHOICES = [
    (NoteVisibility.PRIVATE, "Only me"),
    (NoteVisibility.MENTOR, "Me and other staff"),
    (NoteVisibility.ALL, "Me, staff and the guardian"),
]


def _apply_choices(form, name: str, choices) -> None:
    """Set choices on the field *and* its widget.

    Assigning only `field.choices` leaves the already-constructed widget with
    whatever choices it was built with. For a field whose model has no choices
    that is `None`, so the radio group renders empty - a silently unusable form.
    """
    form.fields[name].choices = choices
    form.fields[name].widget.choices = choices


class EmotionalCheckinForm(forms.ModelForm):
    """The child's own check-in. Date is fixed to today by the view."""

    class Meta:
        model = EmotionalCheckin
        fields = ["mood", "energy", "sleep_quality", "felt_connected", "note", "note_visibility"]
        widgets = {
            "mood": forms.RadioSelect,
            "energy": forms.RadioSelect,
            "sleep_quality": forms.RadioSelect,
            "felt_connected": forms.RadioSelect,
            "note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Anything you want to add? This is optional.",
                }
            ),
            "note_visibility": forms.RadioSelect,
        }
        labels = {
            "mood": "How are you feeling today?",
            "energy": "How much energy do you have?",
            "sleep_quality": "How did you sleep?",
            "felt_connected": "Do you feel connected to people around you?",
            "note": "Do you want to say more?",
            "note_visibility": "Who can read your note?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_choices(self, "mood", MOOD_CHOICES)
        _apply_choices(self, "energy", ENERGY_CHOICES)
        _apply_choices(self, "sleep_quality", QUALITY_CHOICES)
        _apply_choices(self, "felt_connected", CONNECTION_CHOICES)
        _apply_choices(self, "note_visibility", CHILD_NOTE_CHOICES)
        self.fields["note_visibility"].initial = NoteVisibility.PRIVATE
        self.fields["sleep_quality"].required = False
        self.fields["felt_connected"].required = False


class EmotionalObservationForm(forms.ModelForm):
    """An adult's observation of a child.

    `occurred_on` is editable because staff often record something the next
    morning, and forcing "today" would either lose the observation or corrupt
    its date.
    """

    class Meta:
        model = EmotionalCheckin
        fields = [
            "occurred_on",
            "mood",
            "energy",
            "sleep_quality",
            "felt_connected",
            "note",
            "note_visibility",
        ]
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "mood": forms.RadioSelect,
            "energy": forms.RadioSelect,
            "sleep_quality": forms.RadioSelect,
            "felt_connected": forms.RadioSelect,
            "note": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "What did you notice? Behaviour, context, change from usual.",
                }
            ),
            "note_visibility": forms.RadioSelect,
        }
        labels = {
            "occurred_on": "Date observed",
            "mood": "Observed mood",
            "energy": "Observed energy",
            "sleep_quality": "Appeared rested",
            "felt_connected": "Seemed connected to others",
            "note": "Observation",
            "note_visibility": "Who can read this note?",
        }

    def __init__(self, *args, child=None, author=None, source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.child = child
        self.author = author
        self.source = source

        _apply_choices(self, "mood", MOOD_CHOICES)
        _apply_choices(self, "energy", ENERGY_CHOICES)
        _apply_choices(self, "sleep_quality", QUALITY_CHOICES)
        _apply_choices(self, "felt_connected", CONNECTION_CHOICES)
        _apply_choices(self, "note_visibility", ADULT_NOTE_CHOICES)
        self.fields["note_visibility"].initial = NoteVisibility.MENTOR
        self.fields["sleep_quality"].required = False
        self.fields["felt_connected"].required = False
        self.fields["occurred_on"].initial = timezone.localdate()
        self.fields["occurred_on"].widget.attrs["max"] = timezone.localdate().isoformat()

    def clean_occurred_on(self):
        value = self.cleaned_data["occurred_on"]
        if value > timezone.localdate():
            raise forms.ValidationError("The observation cannot be dated in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        date = cleaned.get("occurred_on")
        if not date or self.child is None or self.source is None:
            return cleaned

        # The database has a unique constraint on (child, occurred_on, source).
        # Checking here turns an IntegrityError into a sentence a teacher can
        # act on: another staff member already covered this day.
        existing = (
            EmotionalCheckin.objects.filter(
                child=self.child, occurred_on=date, source=self.source
            )
            .exclude(pk=self.instance.pk)
            .select_related("recorded_by")
            .first()
        )
        if existing is not None:
            who = (
                existing.recorded_by.display_name
                if existing.recorded_by_id
                else "another staff member"
            )
            raise forms.ValidationError(
                f"{who} already recorded an observation for this day. "
                "Only one observation per child, per day, per role is kept."
            )
        return cleaned
