"""
Escala de tolerancia al riesgo Grable-Lytton (13 ítems) — instrumento VALIDADO.

Fuente: Grable, J. E., & Lytton, R. H. (1999). "Financial risk tolerance
revisited: The development of a risk assessment instrument." Financial Services
Review, 8, 163–181.

Reproducción fiel: ítems y puntajes oficiales (rango bruto 13–47). El wording se
adapta al cliente argentino (plazo fijo, dólar, activos duros) PERO la estructura
de opciones y sus puntajes se preservan exactamente, para no romper la validez
psicométrica del instrumento (Cronbach's alpha ≈ 0.77).

Función pura: mismas respuestas → mismo puntaje. No usa IA, no toca DB.

NOTA: es un instrumento de tolerancia DECLARADA (willingness). NO mide la reacción
real bajo estrés; esa señal revelada se captura aparte (open_risk_reaction) y el
Risk Gap compara ambas. Ver ai_layer/risk_scoring.py y docs/RISK_SCORING_THEORY.md.
"""

from __future__ import annotations

from typing import Any

# Cada ítem: clave qN, texto (AR), y opciones [(letra, texto, puntos)].
# Puntajes EXACTOS de Grable-Lytton 1999 (no modificar).
GRABLE_LYTTON_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "q1",
        "text": "¿Cómo te describiría tu mejor amigo en cuanto a tomar riesgos?",
        "options": [
            ("a", "Un verdadero apostador", 4),
            ("b", "Dispuesto a tomar riesgos después de investigar bien", 3),
            ("c", "Cauteloso", 2),
            ("d", "Evito el riesgo a toda costa", 1),
        ],
    },
    {
        "id": "q2",
        "text": "Estás en un programa de TV y podés elegir uno de estos premios. ¿Cuál tomás?",
        "options": [
            ("a", "USD 1.000 en efectivo, seguro", 1),
            ("b", "50% de chance de ganar USD 5.000", 2),
            ("c", "25% de chance de ganar USD 10.000", 3),
            ("d", "5% de chance de ganar USD 100.000", 4),
        ],
    },
    {
        "id": "q3",
        "text": ("Ahorraste para unas vacaciones únicas. Tres semanas antes de salir, "
                 "perdés el trabajo. ¿Qué hacés?"),
        "options": [
            ("a", "Cancelo las vacaciones", 1),
            ("b", "Hago unas vacaciones mucho más modestas", 2),
            ("c", "Voy como estaba planeado; necesito el tiempo para buscar trabajo", 3),
            ("d", "Las extiendo: puede ser mi última chance de viajar a lo grande", 4),
        ],
    },
    {
        "id": "q4",
        "text": "Si recibieras USD 20.000 inesperados para invertir, ¿qué harías?",
        "options": [
            ("a", "Plazo fijo, caja de ahorro o dólar", 1),
            ("b", "Bonos de alta calidad o fondos de bonos", 2),
            ("c", "Acciones o fondos de acciones", 3),
        ],
    },
    {
        "id": "q5",
        "text": "Por tu experiencia, ¿qué tan cómodo estás invirtiendo en acciones?",
        "options": [
            ("a", "Nada cómodo", 1),
            ("b", "Algo cómodo", 2),
            ("c", "Muy cómodo", 3),
        ],
    },
    {
        "id": "q6",
        "text": "Cuando pensás en la palabra «riesgo», ¿qué te viene primero a la cabeza?",
        "options": [
            ("a", "Pérdida", 1),
            ("b", "Incertidumbre", 2),
            ("c", "Oportunidad", 3),
            ("d", "Adrenalina", 4),
        ],
    },
    {
        "id": "q7",
        "text": ("Tenés casi todo en bonos del gobierno (seguros). Dicen que los activos "
                 "duros (oro, inmuebles) van a subir y los bonos pueden caer. ¿Qué hacés?"),
        "options": [
            ("a", "Mantengo los bonos", 1),
            ("b", "Vendo la mitad y la paso a activos duros", 2),
            ("c", "Vendo todo y voy a activos duros", 3),
            ("d", "Vendo todo, voy a activos duros y me endeudo para comprar más", 4),
        ],
    },
    {
        "id": "q8",
        "text": "Dados el mejor y el peor caso de estas inversiones, ¿cuál preferís?",
        "options": [
            ("a", "+USD 200 en el mejor caso; USD 0 en el peor", 1),
            ("b", "+USD 800 en el mejor caso; −USD 200 en el peor", 2),
            ("c", "+USD 2.600 en el mejor caso; −USD 800 en el peor", 3),
            ("d", "+USD 4.800 en el mejor caso; −USD 2.400 en el peor", 4),
        ],
    },
    {
        "id": "q9",
        "text": "Además de lo que ya tenés, te regalan USD 1.000. Tenés que elegir:",
        "options": [
            ("a", "Ganar USD 500 seguro", 1),
            ("b", "50% de ganar USD 1.000 y 50% de no ganar nada", 3),
        ],
    },
    {
        "id": "q10",
        "text": "Además de lo que ya tenés, te regalan USD 2.000. Tenés que elegir:",
        "options": [
            ("a", "Perder USD 500 seguro", 1),
            ("b", "50% de perder USD 1.000 y 50% de no perder nada", 3),
        ],
    },
    {
        "id": "q11",
        "text": ("Heredás USD 100.000 con la condición de invertir TODO en UNA sola "
                 "opción. ¿Cuál elegís?"),
        "options": [
            ("a", "Caja de ahorro o money market", 1),
            ("b", "Un fondo que tiene acciones y bonos", 2),
            ("c", "Una cartera de 15 acciones", 3),
            ("d", "Commodities (oro, plata, petróleo)", 4),
        ],
    },
    {
        "id": "q12",
        "text": "Si tuvieras que invertir USD 20.000, ¿qué mezcla te resulta más atractiva?",
        "options": [
            ("a", "60% bajo riesgo, 30% medio, 10% alto", 1),
            ("b", "30% bajo riesgo, 40% medio, 30% alto", 2),
            ("c", "10% bajo riesgo, 40% medio, 50% alto", 3),
        ],
    },
    {
        "id": "q13",
        "text": ("Un amigo geólogo arma un grupo para financiar una mina de oro "
                 "exploratoria: paga 50 a 100 veces si sale bien, vale cero si fracasa. "
                 "La chance de éxito es 20%. ¿Cuánto invertirías?"),
        "options": [
            ("a", "Nada", 1),
            ("b", "Un mes de sueldo", 2),
            ("c", "Tres meses de sueldo", 3),
            ("d", "Seis meses de sueldo", 4),
        ],
    },
)

# Puntaje bruto mínimo/máximo teórico (todos en 1 → 13; máximos por ítem → 47).
RAW_MIN: int = 13
RAW_MAX: int = 47

# Mapa letra→puntos por ítem, derivado de GRABLE_LYTTON_ITEMS (para scoring O(1)).
_POINTS: dict[str, dict[str, int]] = {
    item["id"]: {letter: pts for (letter, _txt, pts) in item["options"]}
    for item in GRABLE_LYTTON_ITEMS
}


def score_raw(answers: dict[str, str]) -> int:
    """
    Suma los puntajes Grable-Lytton de las respuestas (dict qN→letra).

    Ítems sin responder o con letra inválida puntúan el mínimo del ítem (1),
    para que un cuestionario incompleto tienda a conservador (no a inflar el riesgo).
    Devuelve un entero en [13, 47].
    """
    a = answers or {}
    total = 0
    for item in GRABLE_LYTTON_ITEMS:
        qid = item["id"]
        letter = str(a.get(qid, "")).strip().lower()
        pts = _POINTS[qid].get(letter)
        total += pts if pts is not None else 1  # faltante/ inválido → mínimo
    return total


def raw_to_tolerance_1_10(raw: int) -> float:
    """Mapea el puntaje bruto Grable-Lytton (13–47) a la escala 1–10 del motor."""
    if raw <= RAW_MIN:
        return 1.0
    if raw >= RAW_MAX:
        return 10.0
    return round(1.0 + (raw - RAW_MIN) / (RAW_MAX - RAW_MIN) * 9.0, 1)


def score_tolerance(answers: dict[str, str]) -> float:
    """Atajo: respuestas → tolerancia 1–10 (Grable-Lytton)."""
    return raw_to_tolerance_1_10(score_raw(answers))


# Categoría oficial de G-L sobre el puntaje bruto (para Modo técnico / reporte).
def risk_level_label(raw: int) -> str:
    if raw >= 33:
        return "high"
    if raw >= 29:
        return "above-average"
    if raw >= 23:
        return "average"
    if raw >= 19:
        return "below-average"
    return "low"
