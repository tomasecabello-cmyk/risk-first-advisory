"""
Catálogo de productos complejos (auditoría compliance 2026-07-17, DD-017 ext.).

Un producto "complejo" exige diligencia reforzada de reasonable-basis: el
asesor debe entender (y poder explicar) riesgos que no son evidentes en el
par (instrument_type × perfil) de la matriz de suitability. La marca es
INFORMATIVA y sistemática: no excluye el instrumento ni cambia el optimizador;
viaja en el holding del proposal (`complex_product_note`, flag
`complex_product` en `risk_flags`, reason code SUIT_003) y el report la
formatea como nota de producto.

El catálogo es política de la firma, editable sin tocar el motor: agregar un
tipo acá basta para que el flag y la nota aparezcan en proposals nuevos
(los snapshots ya persistidos no cambian — trazabilidad).
"""

from __future__ import annotations

# instrument_type (valores de universe_layer.InstrumentType) → nota de producto.
# La nota es el texto que ve el asesor y el que se imprime en el report.
COMPLEX_PRODUCT_NOTES: dict[str, str] = {
    "CEDEAR": (
        "Producto complejo: certificado argentino sobre una acción extranjera. "
        "El precio incorpora el ratio de conversión (puede cambiar por "
        "rebasing) y el tipo de cambio CCL implícito, además del riesgo de "
        "la acción subyacente."
    ),
}


def complex_product_note(instrument_type: str | None) -> str | None:
    """
    Nota de producto para un instrument_type, o None si no está catalogado
    como complejo. Acepta None/strings desconocidos sin fallar (holdings
    legacy sin metadata).
    """
    if not instrument_type:
        return None
    return COMPLEX_PRODUCT_NOTES.get(str(instrument_type))
