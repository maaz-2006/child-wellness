"""Forms for entering wellness data.

One audience per form, because the same question means different things to a
child and to a professional.

The child forms are short and concrete: five-point scales with faces, one
optional note, and a plain-language choice about who can read that note. A
nine-year-old should be able to finish in under a minute and should never be
asked to understand the word "visibility".

The adult forms are professional records. They can be back-dated, they separate
structured measurements from the free-text note, and they make the note's
audience explicit at the point of writing - because "who will read this" is the
question staff get wrong most often.
"""

from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import (
    AcademicRecord,
    EmotionalCheckin,
    HabitLog,
    NoteVisibility,
    SocialObservation,
)

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

#: A generic five-point rubric label. The dimension being rated is named in the
#: field label, so the options do not need to repeat it.
RATING_CHOICES = [
    (1, "1 · Very low"),
    (2, "2 · Low"),
    (3, "3 · Mixed"),
    (4, "4 · Good"),
    (5, "5 · Very good"),
]

BREAKFAST_CHOICES = [
    ("", "Not recorded"),
    ("true", "Yes"),
    ("false", "No"),
]


def _apply_choices(form, name: str, choices) -> None:
    """Set choices on the field *and* its widget.

    Assigning only `field.choices` leaves the already-constructed widget with
    whatever choices it was built with. For a field whose model has no choices
    that is `None`, so the radio group renders empty - a silently unusable form.
    """
    form.fields[name].choices = choices
    form.fields[name].widget.choices = choices


class _DatedEntryForm(forms.ModelForm):
    """Shared date handling for adult-entered records.

    Adults routinely record yesterday's observation this morning, so the date is
    editable - but a future date is almost always a typo, and it corrupts any
    trend computed from the record.

    `audience` is accepted by every entry form so the generic create view can
    pass it without knowing which form it is holding; only HabitLogForm uses it.
    """

    def __init__(self, *args, audience: str = "adult", **kwargs):
        self.audience = audience
        super().__init__(*args, **kwargs)

    def _set_date_defaults(self) -> None:
        self.fields["occurred_on"].initial = timezone.localdate()
        self.fields["occurred_on"].widget.attrs["max"] = timezone.localdate().isoformat()

    def clean_occurred_on(self):
        value = self.cleaned_data["occurred_on"]
        if value > timezone.localdate():
            raise forms.ValidationError("This record cannot be dated in the future.")
        return value


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


class EmotionalObservationForm(_DatedEntryForm):
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
        self._set_date_defaults()

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


class AcademicRecordForm(_DatedEntryForm):
    """One assessment or piece of marked work.

    `max_score` is kept separate from `score` because a mark of 8/10 and 80/100
    are the same achievement. Storing a percentage directly would throw away the
    denominator and make it impossible to check the entry later.
    """

    class Meta:
        model = AcademicRecord
        fields = [
            "occurred_on",
            "subject",
            "kind",
            "title",
            "score",
            "max_score",
            "target",
            "note",
            "note_visibility",
        ]
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional context for this result."}
            ),
            "note_visibility": forms.RadioSelect,
        }
        labels = {
            "occurred_on": "Date of assessment",
            "subject": "Subject",
            "kind": "Type",
            "title": "Title",
            "score": "Mark achieved",
            "max_score": "Out of",
            "target": "Target (%)",
            "note": "Note",
            "note_visibility": "Who can read this note?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_choices(self, "note_visibility", ADULT_NOTE_CHOICES)
        self.fields["note_visibility"].initial = NoteVisibility.MENTOR
        self.fields["target"].required = False
        self._set_date_defaults()

    def clean(self):
        cleaned = super().clean()
        score = cleaned.get("score")
        max_score = cleaned.get("max_score")
        target = cleaned.get("target")

        if max_score is not None and max_score <= 0:
            self.add_error("max_score", "The maximum mark must be greater than zero.")
        elif score is not None and max_score is not None and score > max_score:
            self.add_error("score", "The mark cannot be higher than the maximum.")

        if target is not None and not 0 <= target <= 100:
            self.add_error("target", "A target is a percentage between 0 and 100.")

        return cleaned


class SocialObservationForm(_DatedEntryForm):
    """One structured rating of one social dimension, with context.

    Deliberately per-dimension rather than one "social score". A child who
    participates in class but is isolated at break time is not averagely fine;
    the disagreement between dimensions is the finding.
    """

    class Meta:
        model = SocialObservation
        fields = [
            "occurred_on",
            "dimension",
            "rating",
            "context",
            "note",
            "note_visibility",
        ]
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "rating": forms.RadioSelect,
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What did you see, and where?"}
            ),
            "note_visibility": forms.RadioSelect,
        }
        labels = {
            "occurred_on": "Date observed",
            "dimension": "Dimension",
            "rating": "Rating",
            "context": "Where",
            "note": "Observation",
            "note_visibility": "Who can read this note?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_choices(self, "rating", RATING_CHOICES)
        _apply_choices(self, "note_visibility", ADULT_NOTE_CHOICES)
        self.fields["note_visibility"].initial = NoteVisibility.MENTOR
        self._set_date_defaults()


class HabitLogForm(_DatedEntryForm):
    """One day's habits.

    Every measurement is optional on its own, but an entirely empty log is
    rejected: a row with no data is worse than no row, because it looks like the
    child was measured and nothing was found.

    The note's audience wording changes for a child ("Me and my grown-up")
    because the adult words are about staff.
    """

    ate_breakfast = forms.NullBooleanField(
        required=False,
        label="Ate breakfast",
        widget=forms.Select(choices=BREAKFAST_CHOICES),
    )

    class Meta:
        model = HabitLog
        fields = [
            "occurred_on",
            "sleep_hours",
            "activity_minutes",
            "screen_minutes",
            "nutrition_quality",
            "ate_breakfast",
            "note",
            "note_visibility",
        ]
        widgets = {
            "occurred_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "sleep_hours": forms.NumberInput(attrs={"step": "0.1", "min": "0", "max": "24"}),
            "activity_minutes": forms.NumberInput(attrs={"min": "0", "max": "600"}),
            "screen_minutes": forms.NumberInput(attrs={"min": "0", "max": "1440"}),
            "nutrition_quality": forms.RadioSelect,
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Anything that explains today's numbers?"}
            ),
            "note_visibility": forms.RadioSelect,
        }
        labels = {
            "occurred_on": "Date",
            "sleep_hours": "Sleep (hours)",
            "activity_minutes": "Active play / sport (minutes)",
            "screen_minutes": "Screen time (minutes)",
            "nutrition_quality": "Nutrition",
            "note": "Note",
            "note_visibility": "Who can read this note?",
        }

    def __init__(self, *args, audience: str = "adult", **kwargs):
        super().__init__(*args, audience=audience, **kwargs)
        _apply_choices(self, "nutrition_quality", QUALITY_CHOICES)
        if audience == "child":
            _apply_choices(self, "note_visibility", CHILD_NOTE_CHOICES)
            self.fields["note_visibility"].initial = NoteVisibility.PRIVATE
        else:
            _apply_choices(self, "note_visibility", ADULT_NOTE_CHOICES)
            self.fields["note_visibility"].initial = NoteVisibility.MENTOR
        self._set_date_defaults()

    def clean(self):
        cleaned = super().clean()
        measured = [
            cleaned.get("sleep_hours"),
            cleaned.get("activity_minutes"),
            cleaned.get("screen_minutes"),
            cleaned.get("nutrition_quality"),
            cleaned.get("ate_breakfast"),
        ]
        if all(value is None for value in measured):
            raise forms.ValidationError(
                "Record at least one thing: sleep, activity, screen time, "
                "nutrition or breakfast."
            )
        return cleaned
