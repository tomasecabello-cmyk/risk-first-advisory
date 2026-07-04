# Plan de rediseño UX — feedback del usuario (2026-07-04)

> Feedback de primera mano del usuario recorriendo la demo. La causa raíz de casi
> todo: **la página única mezcla tres audiencias** (cliente, asesor, compliance) y
> presenta el flujo como pasos técnicos de API en vez del recorrido real de una
> asesoría. Este doc captura el feedback textual, los hallazgos de las pruebas
> multi-perfil, y el plan por fases.

## Feedback del usuario (resumido)

1. Dos botones de demo: sacar el segundo (habla demasiado de Nitrogen); el botón
   de iniciar quedó arriba y el visitante lo saltea. Mover las bases teóricas a
   una **página aparte, técnica** (el contenido ya existe:
   `RISK_SCORING_THEORY.md`, `METHODOLOGY_NOTES.md`, DD-012).
2. "Recorrido recomendado" + guion: reemplazar por **explicación contextual al
   scrollear** (popup o panel al lado de cada paso), no un bloque de texto arriba.
3. Preparar caso + enviar KYC + analizar con IA = **un solo click** (para el
   cliente es un solo acto: "relleno y envío").
4. ~~Las repreguntas no se van una vez respondidas~~ → **ARREGLADO** (la card
   ahora muestra "respuestas registradas" tras la segunda ronda).
5. Universo: debería ser **todo lo que dan las APIs**; más adelante, limitable
   por bróker. (Ver hallazgos abajo: hoy es una lista fija y le pone un techo
   práctico a los perfiles agresivos.)
6. La verificación de trazabilidad no le sirve al asesor en su día a día — es
   material de compliance. Sacarla de la vista del asesor.
7. El flujo debería contarse como es en la vida real:
   **cliente** rellena KYC → se analiza y sale un primer informe con
   inconsistencias → **asesor** repregunta si hace falta → cliente responde →
   asesor aprueba (o no) → se generan carteras → asesor elige y se las presenta
   como opciones → reporte final al cliente.

## Hallazgos de las pruebas multi-perfil (2026-07-04, fixture CSV sin RFA_LIVE_DATA)

| Perfil KYC | Perfil IA | RN cliente (tol/techo) | Propuesta |
|---|---|---|---|
| Conservador puro | conservador | 10.7 (10.7/15.9) | **INFEASIBLE** |
| Moderado | moderado | 53.3 (53.3/73.7) | 2 variantes, RN 23-33, under_tolerance |
| Agresivo consistente | agresivo | 89.6 (93.3/89.6, capado) | 3 variantes, RN 20-35, **todo under_tolerance** |
| Quiere más de lo que puede | conservador | 11.4 (tol 100 → techo 11.4) | capacity override + risk gap high; **INFEASIBLE** |
| Pánico + trade-off inconsistente | moderado-agresivo | 41.9 (tradeoff 5 vs cuest. 79 → inconsistente ✓) | 3 variantes, GROWTH "aligned" ✓ |

Lecturas:
- **La lógica de riesgo funciona perfecto en los 5 casos** (capacidad acota,
  cross-check de trade-off dispara, risk gap alto con pánico, GROWTH siempre
  marca override).
- **El universo fixture es el cuello de botella**: sin `RFA_LIVE_DATA=1`, los
  perfiles conservadores quedan sin cartera (no hay cash-like de baja vol en el
  CSV — en el universo live sí: BIL/SHV) y el techo práctico de las carteras es
  RN ~36 (todo bonos ARG), así que un agresivo ve todo "más conservadora".
  → La demo debería correrse SIEMPRE con `RFA_LIVE_DATA=1`, y la Fase 3 de
  producto (universo amplio desde las APIs) es lo que destapa la escala completa.
- Los instrumentos son **siempre los mismos** (lista fija); lo que cambia por
  perfil es qué subconjunto y con qué pesos. "Todo lo que dan las APIs" requiere
  universo dinámico (data912/yfinance) + clasificación automática
  (tipo/clase/liquidez) + el pipeline de data quality existente como filtro.

## Respuestas de producto que el rediseño debe hacer visibles

- **¿En base a qué arma la cartera?** (1) Perfil aprobado → RiskBudget
  (`config/risk_profiles.yaml`: vol máxima, drawdown, % equity, etc.);
  (2) preferencias del cliente (tipos de instrumento permitidos, ESG, moneda) →
  filtran el universo ANTES del optimizador (governance → suitability → ESG →
  data, orden fijo I-014); (3) optimizador media-varianza sobre lo que quedó.
  El asesor decide ENTRE variantes con: Risk Number + alineación, diversificación,
  retorno/vol, y si excede el presupuesto (override).
- **¿Qué pasa si el asesor rechaza el perfil?** Queda auditado (I-017), nada
  avanza; el camino es repreguntar → re-análisis → aprobar con `modify` (puede
  aprobar un perfil DISTINTO al propuesto). La UI debe ofrecer ese camino.
- **¿Dónde cae el reporte?** Hoy: se persiste en DB y se muestra en pantalla
  (markdown). Falta: export PDF / entrega al cliente (email o link).
- **¿Para quién es la trazabilidad?** Compliance/auditoría (probar que ninguna
  decisión se alteró). Al asesor no le aporta en el día a día → vista aparte.

## Plan por fases

### Fase UX-1 — la misma página, contada bien (barata, 1-2 sesiones)
- Landing: UN solo CTA ("Iniciar demo"); sacar el bloque/botón de metodología →
  página `methodology.html` técnica (γ CRRA, CVaR, anchors, Grable-Lytton,
  diferenciación de Nitrogen con la tabla de DD-012).
- Fusionar pasos 1-3 en un click ("Cliente completa y envía su perfil").
- Explicaciones contextuales: panel lateral fijo o popover por paso que se
  actualiza al scrollear (reemplaza "recorrido recomendado" + guion).
- Renombrar pasos por actor: "El cliente completa su perfil" / "La IA analiza y
  detecta inconsistencias" / "El asesor revisa y aprueba" / "El asesor elige la
  cartera" / "Reporte para el cliente". Mover "Verificar auditoría" a un bloque
  colapsado "Para compliance".
- Botón de rechazo visible en el paso de aprobación (hoy la demo solo aprueba)
  con el camino: repreguntar → re-análisis → modify.

### Fase UX-2 — separación real por roles (2-4 sesiones)
- `client.html`: SOLO el KYC (con la pregunta de trade-off), responder
  repreguntas, y ver las opciones/reporte que el asesor decida compartir.
- `advisor.html`: bandeja de casos → análisis + Risk Number + gaps → repreguntar /
  aprobar / modificar / rechazar → comparar variantes → presentar opciones A/B →
  generar reporte.
- `compliance.html`: auditoría, trazabilidad, logs de IA redactados.
- Los endpoints ya soportan esto (RBAC advisor/compliance/viewer existe); es
  trabajo de frontend + un mínimo de sesión por token.

### Fase UX-3 — universo dinámico (engancha con Fase 3 de producto)
- Universo generado desde las APIs (data912 + yfinance) en vez del CSV/lista
  fija; concepto de "bróker" como filtro de disponibilidad; el pipeline de
  data quality decide qué entra. Esto destapa la escala completa del Risk
  Number para perfiles agresivos y arregla el infeasible de conservadores
  incluso sin curar listas a mano.

## Cómo correr la demo HOY para que luzca (mientras tanto)

```powershell
$env:RFA_DEMO_MODE = "1"; $env:RFA_LIVE_DATA = "1"
python -m uvicorn risk_first_advisory.api_layer.main:app --port 8000
# con RFA_LIVE_DATA los conservadores arman DEFENSIVE (BIL/SHV) y hay equities.
```
