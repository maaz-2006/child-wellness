"""Offline evaluation of a deliberately simple classifier.

**This module is not in the production decision path.** It does not write alerts,
scores or any per-child prediction. It exists so the report can answer a modest,
falsifiable question:

    Can a plain logistic regression, trained only on the same structured
    features the deterministic rules already use, separate the synthetic
    cohort's labelled difficult periods from its stable periods when every
    held-out child is a child the model has never seen?

That is a methodological check on the features, not a claim that the platform
can predict a child's future. Leave-one-child-out validation is used because the
same child appears at several snapshots; splitting by snapshot would leak that
child's pattern into training and produce a flattering number.

Design choices worth defending:

* **No free text.** Features come from stored scores, the child's own weekly
  scores and two guardian ratings. Notes and messages are never read.
* **Labels are current state, not a forecast.** A declining archetype is positive
  from its simulated onset onward; a recovering archetype is positive in the low
  period before it recovers; a healthy archetype is negative. This is a
  state-classification benchmark, not an early-warning evaluation. The alert
  backtest remains the early-warning measurement.
* **Sparse children are excluded.** Their problem is missing data. Counting a
  recording artefact as a negative would teach the model that absence means
  wellness.
* **Pure Python.** No numpy, scikit-learn or extra deployment dependency. IRLS
  converges quickly on 13 standardised features.
* **Threshold 0.5 and fixed L2.** No hyper-parameter search on the evaluation
  data, which would quietly turn the benchmark into an optimistic fit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from math import exp
from statistics import mean, pstdev

from django.utils import timezone

from analytics import scoring
from analytics.models import ScenarioLabel
from feedback.models import PulseResponse

MODEL_VERSION = "1.0"
ALGORITHM = "logistic_regression"
TASK = "Current labelled difficulty from structured wellness features"
SNAPSHOTS = scoring.TREND_PERIODS
PULSE_LOOKBACK_DAYS = 21
PRIOR_WINDOWS = 4
MIN_PRIOR_WINDOWS = 3
MIN_EXAMPLES = 20
MIN_CLASS_EXAMPLES = 4
THRESHOLD = 0.5
L2 = 0.05
IRLS_ITERATIONS = 30

#: Ordered feature names. The model report stores this list so an old report is
#: still interpretable if a later version adds a feature.
FEATURE_NAMES = (
    "overall_latest",
    "overall_prior_mean",
    "overall_delta_4w",
    "overall_baseline_z",
    "emotional_latest",
    "academic_latest",
    "social_latest",
    "habits_latest",
    "low_domain_share",
    "domain_coverage",
    "pulse_wellbeing",
    "pulse_support",
    "pulse_missing",
)

FEATURE_LABELS = {
    "overall_latest": "Latest overall score",
    "overall_prior_mean": "Mean of prior overall scores",
    "overall_delta_4w": "Change over four weeks",
    "overall_baseline_z": "Deviation from own recent range (SD)",
    "emotional_latest": "Latest emotional score",
    "academic_latest": "Latest academic score",
    "social_latest": "Latest social score",
    "habits_latest": "Latest habits score",
    "low_domain_share": "Share of domains at or below 50",
    "domain_coverage": "Domains with data",
    "pulse_wellbeing": "Latest guardian wellbeing rating",
    "pulse_support": "Latest guardian support rating",
    "pulse_missing": "No recent guardian pulse",
}

METRIC_LABELS = {
    "accuracy": ("Accuracy", "Share of held-out snapshots classified correctly"),
    "precision": ("Precision", "Of those flagged, the share in a difficult period"),
    "recall": ("Recall", "Of difficult periods, the share flagged"),
    "f1": ("F1", "Harmonic mean of precision and recall"),
    "specificity": ("Specificity", "Of stable periods, the share left unflagged"),
    "auc": ("ROC AUC", "Ranking quality across all thresholds"),
    "prevalence": ("Positive share", "Base rate of difficult periods in the data"),
    "brier": ("Brier score", "Mean squared probability error; lower is better"),
}


@dataclass(frozen=True)
class Example:
    """One child at one weekly snapshot."""

    child_id: int
    snapshot: date
    label: int
    features: tuple[float, ...]


@dataclass
class Dataset:
    examples: list[Example]
    children: int = 0
    positive: int = 0
    negative: int = 0
    skipped_sparse: int = 0
    skipped_no_consent: int = 0
    skipped_no_label: int = 0


# ---------------------------------------------------------------------------
# Labels and features
# ---------------------------------------------------------------------------
def label_for(label: ScenarioLabel, snapshot: date) -> int | None:
    """Whether this snapshot falls in a labelled difficult period.

    `None` means the archetype has no wellness label we are willing to learn
    from (sparse data), so the example is excluded rather than guessed.
    """
    archetype = label.archetype
    onset = label.onset_date

    if archetype == ScenarioLabel.Archetype.HEALTHY:
        return 0
    if archetype in {
        ScenarioLabel.Archetype.GRADUAL_DECLINE,
        ScenarioLabel.Archetype.SUDDEN_EVENT,
    }:
        if onset is None:
            return 0
        return int(snapshot >= onset)
    if archetype == ScenarioLabel.Archetype.RECOVERING:
        if onset is None:
            return 0
        return int(snapshot < onset)
    return None


def _series(rows, domain: str, snapshot: date) -> list[tuple[date, float]]:
    """Stored score rows for one domain up to and including this snapshot."""
    entries = [
        (row.period_end, float(row.score))
        for row in rows
        if row.domain == domain and row.period_end <= snapshot
    ]
    entries.sort(key=lambda item: item[0])
    return entries


def _domain_value(rows, domain: str, snapshot: date) -> float | None:
    series = _series(rows, domain, snapshot)
    return series[-1][1] if series else None


def _pulse_value(pulses, snapshot: date):
    """Latest guardian pulse in the three weeks before the snapshot."""
    start = snapshot - timedelta(days=PULSE_LOOKBACK_DAYS)
    recent = [
        row for row in pulses if start <= row[0] <= snapshot
    ]
    if not recent:
        return None
    return max(recent, key=lambda row: row[0])


def features_for(rows, pulses, snapshot: date) -> tuple[float, ...] | None:
    """Feature vector for one snapshot, or `None` when there is no overall score.

    A snapshot with no overall score is not a data point about wellness. Dropping
    it is the same decision the scoring engine makes when it writes no row at
    all: absence is not zero.
    """
    overall = _series(rows, scoring.OVERALL, snapshot)
    if not overall:
        return None

    latest = overall[-1][1]
    prior = [value for _end, value in overall[-(PRIOR_WINDOWS + 1):-1]]
    prior_mean = mean(prior) if prior else latest
    if len(prior) >= MIN_PRIOR_WINDOWS:
        spread = max(pstdev(prior), 5.0)
        baseline_z = (latest - prior_mean) / spread
        baseline_z = max(-3.0, min(3.0, baseline_z))
    else:
        baseline_z = 0.0
    # Four weeks back is the fifth-from-last weekly score; the previous four
    # windows are the reference range.
    delta = latest - overall[-5][1] if len(overall) >= 5 else 0.0

    domain_values = []
    for domain in scoring.DOMAINS:
        value = _domain_value(rows, domain, snapshot)
        if value is not None:
            domain_values.append(value)
    present = len(domain_values)
    low = sum(1 for value in domain_values if value <= 50.0)

    pulse = _pulse_value(pulses, snapshot)
    if pulse is None:
        pulse_wellbeing = 0.5
        pulse_support = 0.5
        pulse_missing = 1.0
    else:
        pulse_wellbeing = (pulse[1] - 1) / 4.0
        pulse_support = ((pulse[2] if pulse[2] is not None else 3) - 1) / 4.0
        pulse_missing = 0.0

    return (
        latest / 100.0,
        prior_mean / 100.0,
        delta / 100.0,
        baseline_z,
        (_domain_value(rows, "emotional", snapshot) or 0.0) / 100.0,
        (_domain_value(rows, "academic", snapshot) or 0.0) / 100.0,
        (_domain_value(rows, "social", snapshot) or 0.0) / 100.0,
        (_domain_value(rows, "habits", snapshot) or 0.0) / 100.0,
        low / 4.0,
        present / 4.0,
        pulse_wellbeing,
        pulse_support,
        pulse_missing,
    )


def build_dataset(as_of: date | None = None) -> Dataset:
    """Every usable (child, weekly snapshot) example with its state label."""
    from analytics.models import DomainScore
    from children.models import Child

    as_of = as_of or timezone.localdate()
    dataset = Dataset(examples=[])
    windows = scoring.periods(as_of, SNAPSHOTS)

    labels = (
        ScenarioLabel.objects.select_related("child")
        .filter(child__is_active=True)
        .order_by("child_id")
    )
    for label in labels:
        child = label.child
        if not child.has_consent:
            dataset.skipped_no_consent += 1
            continue
        if label.archetype == ScenarioLabel.Archetype.SPARSE:
            dataset.skipped_sparse += 1
            continue

        rows = list(DomainScore.objects.filter(child=child))
        pulses = list(
            PulseResponse.objects.filter(child=child).values_list(
                "week_start", "wellbeing", "support"
            )
        )
        for window in windows:
            outcome = label_for(label, window.end)
            if outcome is None:
                dataset.skipped_no_label += 1
                continue
            vector = features_for(rows, pulses, window.end)
            if vector is None:
                # Missing overall data is a recording gap, not a negative.
                continue
            dataset.examples.append(
                Example(
                    child_id=child.pk,
                    snapshot=window.end,
                    label=outcome,
                    features=vector,
                )
            )

    dataset.children = len(
        Child.objects.filter(
            pk__in={example.child_id for example in dataset.examples}
        )
    )
    dataset.positive = sum(1 for example in dataset.examples if example.label)
    dataset.negative = len(dataset.examples) - dataset.positive
    return dataset


# ---------------------------------------------------------------------------
# Standardisation and IRLS
# ---------------------------------------------------------------------------
def _fit_scaler(examples: list[Example]) -> tuple[list[float], list[float]]:
    width = len(examples[0].features)
    means = [mean(row.features[index] for row in examples) for index in range(width)]
    stds = [
        pstdev(row.features[index] for row in examples) or 1.0
        for index in range(width)
    ]
    return means, stds


def _scale(example: Example, means, stds) -> list[float]:
    return [
        (value - means[index]) / stds[index]
        for index, value in enumerate(example.features)
    ]


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + exp(-value))
    exp_value = exp(value)
    return exp_value / (1.0 + exp_value)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. `None` if singular."""
    size = len(vector)
    work = [row[:] + [vector[index]] for index, row in enumerate(matrix)]

    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1e-12:
            return None
        if pivot != column:
            work[column], work[pivot] = work[pivot], work[column]

        divisor = work[column][column]
        for index in range(column, size + 1):
            work[column][index] /= divisor

        for row in range(size):
            if row == column:
                continue
            factor = work[row][column]
            if factor == 0:
                continue
            for index in range(column, size + 1):
                work[row][index] -= factor * work[column][index]

    return [work[index][size] for index in range(size)]


def train(
    rows: list[list[float]],
    labels: list[int],
    *,
    l2: float = L2,
    iterations: int = IRLS_ITERATIONS,
) -> tuple[list[float], float]:
    """Fit a ridge-penalised logistic regression with Newton-Raphson (IRLS)."""
    if not rows:
        raise ValueError("No training rows.")
    width = len(rows[0])
    weights = [0.0] * width
    bias = 0.0

    for _iteration in range(iterations):
        probabilities = [
            _sigmoid(sum(w * x for w, x in zip(weights, row)) + bias)
            for row in rows
        ]

        gradient_w = [0.0] * width
        gradient_b = 0.0
        hessian = [[0.0] * (width + 1) for _ in range(width + 1)]

        for row, label, probability in zip(rows, labels, probabilities):
            error = probability - label
            weight = max(probability * (1.0 - probability), 1e-6)

            for left in range(width):
                gradient_w[left] += error * row[left]
                hessian[left][width] += weight * row[left]
                for right in range(width):
                    hessian[left][right] += weight * row[left] * row[right]
            gradient_b += error
            hessian[width][width] += weight

        for index in range(width):
            gradient_w[index] += l2 * weights[index]
            hessian[index][index] += l2 + 1e-9
        hessian[width][width] += 1e-9

        gradient = gradient_w + [gradient_b]
        step = _solve(hessian, gradient)
        if step is None:
            break

        for index in range(width):
            weights[index] -= step[index]
        bias -= step[width]

        if max(abs(value) for value in step) < 1e-7:
            break

    return weights, bias


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def _auc(labels: list[int], probabilities: list[float]) -> float | None:
    positives = [
        probability
        for label, probability in zip(labels, probabilities)
        if label == 1
    ]
    negatives = [
        probability
        for label, probability in zip(labels, probabilities)
        if label == 0
    ]
    if not positives or not negatives:
        return None

    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _metrics(labels: list[int], predictions: list[int], probabilities: list[float]):
    tp = sum(1 for y, p in zip(labels, predictions) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(labels, predictions) if y == 0 and p == 1)
    tn = sum(1 for y, p in zip(labels, predictions) if y == 0 and p == 0)
    fn = sum(1 for y, p in zip(labels, predictions) if y == 1 and p == 0)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    accuracy = (tp + tn) / len(labels) if labels else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    brier = (
        sum((probability - label) ** 2 for label, probability in zip(labels, probabilities))
        / len(labels)
        if labels
        else 0.0
    )
    auc = _auc(labels, probabilities)

    metrics = {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "specificity": round(specificity, 4),
        "auc": round(auc, 4) if auc is not None else None,
        "prevalence": round(sum(labels) / len(labels), 4) if labels else 0.0,
        "brier": round(brier, 4),
    }
    confusion = {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
    return metrics, confusion


def evaluate_loocv(examples: list[Example], *, l2: float = L2):
    """Leave-one-child-out predictions and metrics.

    Every example from the held-out child is predicted by a model trained on the
    other children only. That is the right split for repeated snapshots; a
    row-wise split would let the model memorise the child rather than the pattern.
    """
    by_child: dict[int, list[Example]] = defaultdict(list)
    for example in examples:
        by_child[example.child_id].append(example)

    labels: list[int] = []
    predictions: list[int] = []
    probabilities: list[float] = []
    folds = 0
    skipped_folds = 0

    for child_id in sorted(by_child):
        held_out = by_child[child_id]
        training = [
            example for example in examples if example.child_id != child_id
        ]
        if len({example.label for example in training}) < 2:
            skipped_folds += 1
            continue

        means, stds = _fit_scaler(training)
        rows = [_scale(example, means, stds) for example in training]
        train_labels = [example.label for example in training]
        weights, bias = train(rows, train_labels, l2=l2)

        for example in held_out:
            row = _scale(example, means, stds)
            probability = _sigmoid(
                sum(weight * value for weight, value in zip(weights, row)) + bias
            )
            labels.append(example.label)
            predictions.append(int(probability >= THRESHOLD))
            probabilities.append(probability)
        folds += 1

    metrics, confusion = _metrics(labels, predictions, probabilities)
    return {
        "metrics": metrics,
        "confusion": confusion,
        "folds": folds,
        "skipped_folds": skipped_folds,
        "predictions": len(labels),
    }


def _coefficients(examples: list[Example], *, l2: float = L2):
    """A full-cohort fit for interpretation only, never for evaluation."""
    if len({example.label for example in examples}) < 2:
        return [], None, [], []
    means, stds = _fit_scaler(examples)
    rows = [_scale(example, means, stds) for example in examples]
    labels = [example.label for example in examples]
    weights, bias = train(rows, labels, l2=l2)

    rows_out = []
    for index, name in enumerate(FEATURE_NAMES):
        rows_out.append(
            {
                "name": name,
                "label": FEATURE_LABELS.get(name, name),
                "weight": round(weights[index], 4),
                "mean": round(means[index], 4),
                "std": round(stds[index], 4),
            }
        )
    return rows_out, round(bias, 4), means, stds


def evaluate_and_store(as_of: date | None = None):
    """Run the benchmark and persist a `ModelReport`. Returns the report."""
    from analytics.models import ModelReport

    as_of = as_of or timezone.localdate()
    dataset = build_dataset(as_of)

    notes = (
        "Offline benchmark only. No alert, score or per-child prediction is "
        "produced by this model. Labels are the synthetic cohort's current "
        "state (declining from onset, recovering before its recovery), not a "
        "forecast. Validation is leave-one-child-out. Sparse children are "
        "excluded because missing data is not a wellness label. Guardian pulse "
        "ratings are features; no free text is read."
    )

    if (
        len(dataset.examples) < MIN_EXAMPLES
        or dataset.positive < MIN_CLASS_EXAMPLES
        or dataset.negative < MIN_CLASS_EXAMPLES
    ):
        return ModelReport.objects.create(
            as_of=as_of,
            method_version=MODEL_VERSION,
            status=ModelReport.Status.INSUFFICIENT_DATA,
            algorithm=ALGORITHM,
            task=TASK,
            n_children=dataset.children,
            n_examples=len(dataset.examples),
            n_positive=dataset.positive,
            n_negative=dataset.negative,
            threshold=THRESHOLD,
            l2=L2,
            feature_names=list(FEATURE_NAMES),
            notes=notes
            + " Insufficient usable examples or class balance for a "
            "leave-one-child-out benchmark; run seed_demo first.",
        )

    evaluation = evaluate_loocv(dataset.examples)
    coefficients, intercept, _means, _stds = _coefficients(dataset.examples)

    return ModelReport.objects.create(
        as_of=as_of,
        method_version=MODEL_VERSION,
        status=ModelReport.Status.OK,
        algorithm=ALGORITHM,
        task=TASK,
        n_children=dataset.children,
        n_examples=len(dataset.examples),
        n_positive=dataset.positive,
        n_negative=dataset.negative,
        folds=evaluation["folds"],
        threshold=THRESHOLD,
        l2=L2,
        metrics=evaluation["metrics"],
        confusion=evaluation["confusion"],
        feature_names=list(FEATURE_NAMES),
        coefficients=coefficients,
        intercept=intercept,
        notes=notes,
    )
