"""
Tests de la escala Grable-Lytton (13 ítems) — fidelidad de puntajes.

Verifica que la reproducción respeta los puntajes oficiales (rango 13–47) y el
mapeo a la escala 1–10 del motor. Fuente: Grable & Lytton (1999), Financial
Services Review 8, 163–181.
"""

from __future__ import annotations

from risk_first_advisory.ai_layer.grable_lytton import (
    GRABLE_LYTTON_ITEMS,
    RAW_MAX,
    RAW_MIN,
    raw_to_tolerance_1_10,
    risk_level_label,
    score_raw,
    score_tolerance,
)

# Letra de máximo y mínimo puntaje por ítem (derivadas de la tabla oficial).
_MAX_LETTER = {it["id"]: max(it["options"], key=lambda o: o[2])[0] for it in GRABLE_LYTTON_ITEMS}
_MIN_LETTER = {it["id"]: min(it["options"], key=lambda o: o[2])[0] for it in GRABLE_LYTTON_ITEMS}


def test_thirteen_items():
    assert len(GRABLE_LYTTON_ITEMS) == 13
    assert {it["id"] for it in GRABLE_LYTTON_ITEMS} == {f"q{i}" for i in range(1, 14)}


def test_all_min_is_raw_13_tolerance_1():
    raw = score_raw(_MIN_LETTER)
    assert raw == RAW_MIN == 13
    assert score_tolerance(_MIN_LETTER) == 1.0


def test_all_max_is_raw_47_tolerance_10():
    raw = score_raw(_MAX_LETTER)
    assert raw == RAW_MAX == 47
    assert score_tolerance(_MAX_LETTER) == 10.0


def test_missing_answers_score_minimum_conservative():
    # Cuestionario vacío → todos los ítems al mínimo (1) → raw 13 → tolerancia 1.0.
    assert score_raw({}) == 13
    assert score_tolerance({}) == 1.0


def test_invalid_letter_scores_minimum():
    assert score_raw({"q1": "z", "q2": "x"}) == 13  # letras inválidas → mínimo


def test_item1_is_reverse_scored():
    # Ítem 1: "apostador" (a) = 4 puntos; "evito riesgo" (d) = 1. Está invertido.
    pts = {letter: p for (letter, _t, p) in GRABLE_LYTTON_ITEMS[0]["options"]}
    assert pts["a"] == 4 and pts["d"] == 1


def test_raw_to_tolerance_is_monotonic_and_bounded():
    assert raw_to_tolerance_1_10(13) == 1.0
    assert raw_to_tolerance_1_10(47) == 10.0
    mid = raw_to_tolerance_1_10(30)
    assert 1.0 < mid < 10.0
    assert raw_to_tolerance_1_10(5) == 1.0   # clamp
    assert raw_to_tolerance_1_10(99) == 10.0  # clamp


def test_risk_level_labels_official_bands():
    assert risk_level_label(13) == "low"          # 0-18
    assert risk_level_label(20) == "below-average"  # 19-22
    assert risk_level_label(25) == "average"       # 23-28
    assert risk_level_label(30) == "above-average"  # 29-32
    assert risk_level_label(40) == "high"          # 33-47


def test_deterministic():
    ans = {"q1": "b", "q2": "c", "q5": "b"}
    assert score_raw(ans) == score_raw(ans)
