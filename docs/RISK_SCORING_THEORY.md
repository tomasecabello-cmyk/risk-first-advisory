# Risk Scoring — base teórica y algoritmo propio (no patentado)

Referencia para el motor de perfilado de riesgo (M-Engine / Risk Gap). Documenta la
teoría libre sobre la que se para Nitrogen/Riskalyze, qué de su método está patentado
(y conviene NO replicar), el toolkit académico de dominio público, y un algoritmo
propio, diferenciado, que podemos construir y eventualmente intentar patentar.

> **Aviso:** este documento NO es asesoramiento legal. La teoría académica es libre;
> la patente de un tercero cubre su método específico. Antes de comercializar, hacer
> un **freedom-to-operate (FTO)** y consultar con un agente/abogado de patentes.

---

## 1. Teoría base (libre, no patentable)

Nitrogen/Riskalyze se apoya en **Prospect Theory** (Kahneman & Tversky, 1979; Nobel de
Kahneman, 2002). Elementos centrales:

- **Enfoque descriptivo**: cómo la gente decide *de hecho* bajo incertidumbre (no cómo
  *debería* según utilidad esperada clásica).
- **Aversión a la pérdida**: una pérdida pesa ~2x un equivalente de ganancia.
- **Dependencia del punto de referencia**: las ganancias/pérdidas se evalúan respecto de
  un punto de referencia, no en niveles absolutos de riqueza.

Esto es academia pública y se puede usar libremente. Lo que NO se puede es copiar la
*implementación* específica de un tercero.

## 2. Qué hace Nitrogen exactamente (su método — distintivo/patentado, NO replicar)

Dos capas:

1. **Tolerancia del cliente → "Risk Number" 1–99.** Elicitan con apuestas expresadas en
   **montos en dólares reales y significativos** para el inversor ("¿qué pérdida sería
   devastadora? ¿qué ganancia aceptable?"), con varias preguntas cuantitativas para cazar
   inconsistencias. Rechazan explícitamente porcentajes abstractos y preguntas tipo
   "¿qué auto manejás?".
2. **Riesgo de la cartera → mismo 1–99.** Calculan un **rango de probabilidad del 95% a
   6 meses** (ej. −7% a +12%) y lo mapean a un umbral de caída: RN 50 ≈ −9.5%, RN 70 ≈
   −15%, RN 85 ≈ −20%. "Alineación" = la caída 95% de la cartera entra en la tolerancia
   del cliente.

**Distintivo a evitar:** la escala **1–99**, la apuesta en dólares "devastador/aceptable",
y el mapeo **95% / 6 meses → score**.

## 3. Toolkit académico libre que SÍ podemos usar

- **Grable & Lytton (1999)** — escala de tolerancia al riesgo de 13 ítems, validada
  (Cronbach α ≈ 0.77), pública y muy usada. 8 categorías: garantizado-vs-probable,
  elección general de riesgo, pérdida segura vs ganancia segura, riesgo como
  experiencia, riesgo como confort, riesgo especulativo, prospect theory, riesgo de
  inversión. (Escribir ítems propios inspirados en las categorías; no copiar los suyos.)
- **Utilidad esperada + CRRA/CARA** y **certainty equivalent**: de respuestas a apuestas
  se deriva un coeficiente de aversión al riesgo γ.
- **Métricas de riesgo de cartera**: **CVaR / Expected Shortfall** (riesgo de cola),
  **semidesvío / Sortino** (downside), **distribución de drawdown por Monte Carlo**.

## 4. Algoritmo propio propuesto (diferenciado, no patentado)

Atado a los campos de KYC ya existentes (`emotional_loss_tolerance_pct`,
`financial_loss_capacity_pct`, `open_risk_reaction`).

### Capa A — perfil DECLARADO (stated)
- Cuestionario propio estilo Grable-Lytton → score.
- Opcional: apuesta 50/50 → **certainty equivalent** → coeficiente **CRRA γ**.
  Para una apuesta de ganar `G` o perder `L` con prob 0.5 sobre riqueza `W`, el γ que
  hace al cliente indiferente con un monto seguro `C` resuelve:
  ```
  0.5 · u(W+G) + 0.5 · u(W−L) = u(W+C),   con   u(x) = x^(1−γ) / (1−γ)
  ```
- Mapear γ (o el score) a **los 5 perfiles del sistema** (conservador → agresivo),
  NO a un 1–99.

### Capa B — señal REVELADA (revealed) = el Risk Gap
- La respuesta al escenario de estrés (`open_risk_reaction`) da una tolerancia
  *revelada*. El output no es solo un número: es el **gap entre declarado y revelado**,
  con preguntas para que el asesor lo confirme.
- **Nitrogen NO hace esto** (ellos entregan un número). Acá está el diferenciador
  defendible: detectar y exponer la inconsistencia + asesor en el loop.

### Capa C — riesgo de cartera (distinto del 95%/6-meses)
- **CVaR al 95%** (pérdida esperada en el peor 5%) y/o **Sortino**, sobre un horizonte
  **configurable** (no fijo a 6 meses), presentado como **probabilidad de superar el
  "umbral de pérdida devastadora" que el cliente define** — no como un score propietario.
- Alinear: γ/perfil → CVaR máximo aceptable.

### Por qué no infringe (ejes de diferenciación)
| Eje | Nitrogen | Nuestro |
|---|---|---|
| Escala de tolerancia | 1–99 | γ (CRRA) / 5 perfiles |
| Métrica de cartera | rango 95% | CVaR / Sortino |
| Horizonte | 6 meses fijo | configurable |
| Feature central | un número | **gap declarado-vs-revelado + asesor** |

## 5. Notas de patentabilidad (para cuando se busque protección)

- **Prior art conocido** (a citar / sortear): Riskalyze/Nitrogen (Risk Number),
  Grable-Lytton (escala), FinaMetrica (psicometría), VaR/CVaR (finanzas cuantitativas).
- **Candidato a reivindicación novedosa/no-obvia**: el *método* de **detectar la
  inconsistencia entre el perfil de riesgo declarado y el revelado por escenarios de
  estrés, generar preguntas de confirmación dirigidas, y bloquear/condicionar la
  construcción de cartera a la firma del asesor** (human-in-the-loop auditado). Es decir,
  el sistema **risk-first + Risk Gap + override auditado**, no el scoring per se (el
  scoring solo probablemente choca con prior art).
- **Requisitos prácticos**: documentar el método con precisión (este doc + un method
  spec), fecha de invención, y **FTO + abogado de patentes** antes de comercializar.
- No reverse-engineerear ni copiar preguntas/escala de terceros.

## 6. Encaje con el producto
Esto es el **M-Engine** diferido: cuestionario tipo Grable-Lytton (declarado) + escenario
de estrés (revelado) → γ/perfil → chequeo de cartera por CVaR, con el **Risk Gap** como
corazón y el override auditado como control. Ver `docs/METHODOLOGY_NOTES.md` y
`ai_layer/risk_gap.py`.

## Fuentes
- Nitrogen 101 — What is Prospect Theory? — https://nitrogenwealth.com/riskalyze-101-what-is-prospect-theory/
- Nitrogen — Understanding Risk Numbers — https://nitrogenwealth.com/blog/riskalyze-101-risk-number/
- Grable & Lytton risk-tolerance scale: 15-year retrospective (Financial Services Review) — https://openjournals.libs.uga.edu/fsr/article/view/3240
- Measuring the Perception of Financial Risk Tolerance (AFCPE) — https://www.afcpe.org/wp-content/uploads/2018/10/vol_21_issue_2_gilliam_chatterjee_grable.pdf
- Traditional vs psychometric relative risk tolerance (ScienceDirect) — https://www.sciencedirect.com/science/article/abs/pii/S1544612318307293
