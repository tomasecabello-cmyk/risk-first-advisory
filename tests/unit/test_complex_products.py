"""
Tests del catálogo de productos complejos (DD-017 ext.).
"""

from __future__ import annotations

from risk_first_advisory.rules_layer.complex_products import (
    COMPLEX_PRODUCT_NOTES,
    complex_product_note,
)


def test_cedear_is_catalogued_complex():
    note = complex_product_note("CEDEAR")
    assert note is not None
    assert "ratio" in note.lower()
    assert "ccl" in note.lower()


def test_simple_types_return_none():
    for itype in ("ETF", "STOCK", "SOVEREIGN_BOND", "MONEY_MARKET"):
        assert complex_product_note(itype) is None


def test_none_and_unknown_tolerated():
    assert complex_product_note(None) is None
    assert complex_product_note("") is None
    assert complex_product_note("NO_EXISTE") is None


def test_catalog_notes_are_nonempty_strings():
    """Cada entrada del catálogo debe tener nota presentable (va al report)."""
    for itype, note in COMPLEX_PRODUCT_NOTES.items():
        assert isinstance(itype, str) and itype.strip()
        assert isinstance(note, str) and len(note.strip()) > 20
