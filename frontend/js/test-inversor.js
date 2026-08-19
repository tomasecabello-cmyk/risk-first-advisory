// Risk-First Advisory — Test de inversor (página autónoma)
// ---------------------------------------------------------------------------
// Escala Grable-Lytton (1999), 13 ítems. Esta página es DEMOSTRATIVA y corre
// 100% en el browser: no llama a la API, no persiste nada, no crea un case.
// Sirve para mostrar el instrumento aislado (clase, defensa, presentación).
//
// ⚠ Los ítems y puntajes son un espejo de ai_layer/grable_lytton.py, que es la
// fuente de verdad del motor. Si cambian allá, actualizar acá (y al revés).
// El scoring del flujo real ocurre server-side; esto es sólo la vitrina.
//
// Mapeo a la numeración original del paper (se descartaron los ítems 4, 7, 9,
// 10, 11, 13 y 15 en el análisis factorial) y al factor donde carga cada uno:
//   F1 Riesgo de inversión      → ítems originales 5, 6, 14, 18, 19
//   F2 Confort y experiencia    → ítems originales 1, 3, 8, 12, 20
//   F3 Riesgo especulativo      → ítems originales 2, 16, 17
// Classic script, sin módulos: se abre con file:// o con http.server.

const GL_FACTORS = {
  F1: { label: "Riesgo de inversión", pill: "pill-blue",   alpha: "0,720" },
  F2: { label: "Confort y experiencia", pill: "pill-green", alpha: "0,502" },
  F3: { label: "Riesgo especulativo", pill: "pill-violet",  alpha: "0,443" },
};

const GL_ITEMS = [
  {
    id: "q1", orig: 1, factor: "F2",
    text: "¿Cómo te describiría tu mejor amigo en cuanto a tomar riesgos?",
    options: [
      ["a", "Un verdadero apostador", 4],
      ["b", "Dispuesto a tomar riesgos después de investigar bien", 3],
      ["c", "Cauteloso", 2],
      ["d", "Evito el riesgo a toda costa", 1],
    ],
  },
  {
    id: "q2", orig: 2, factor: "F3",
    text: "Estás en un programa de TV y podés elegir uno de estos premios. ¿Cuál tomás?",
    options: [
      ["a", "USD 1.000 en efectivo, seguro", 1],
      ["b", "50% de chance de ganar USD 5.000", 2],
      ["c", "25% de chance de ganar USD 10.000", 3],
      ["d", "5% de chance de ganar USD 100.000", 4],
    ],
  },
  {
    id: "q3", orig: 3, factor: "F2",
    text: "Ahorraste para unas vacaciones únicas. Tres semanas antes de salir, perdés el trabajo. ¿Qué hacés?",
    options: [
      ["a", "Cancelo las vacaciones", 1],
      ["b", "Hago unas vacaciones mucho más modestas", 2],
      ["c", "Voy como estaba planeado; necesito el tiempo para buscar trabajo", 3],
      ["d", "Las extiendo: puede ser mi última chance de viajar a lo grande", 4],
    ],
  },
  {
    id: "q4", orig: 5, factor: "F1",
    text: "Si recibieras USD 20.000 inesperados para invertir, ¿qué harías?",
    options: [
      ["a", "Plazo fijo, caja de ahorro o dólar", 1],
      ["b", "Bonos de alta calidad o fondos de bonos", 2],
      ["c", "Acciones o fondos de acciones", 3],
      ["x", "No lo entiendo / no estoy seguro", 1],
    ],
  },
  {
    id: "q5", orig: 6, factor: "F1",
    text: "Por tu experiencia, ¿qué tan cómodo estás invirtiendo en acciones?",
    options: [
      ["a", "Nada cómodo", 1],
      ["b", "Algo cómodo", 2],
      ["c", "Muy cómodo", 3],
    ],
  },
  {
    id: "q6", orig: 8, factor: "F2",
    text: "Cuando pensás en la palabra «riesgo», ¿qué te viene primero a la cabeza?",
    options: [
      ["a", "Pérdida", 1],
      ["b", "Incertidumbre", 2],
      ["c", "Oportunidad", 3],
      ["d", "Adrenalina", 4],
    ],
  },
  {
    id: "q7", orig: 12, factor: "F2",
    text: "Tenés casi todo en bonos del gobierno (seguros). Dicen que los activos duros (oro, inmuebles) van a subir y los bonos pueden caer. ¿Qué hacés?",
    options: [
      ["a", "Mantengo los bonos", 1],
      ["b", "Vendo la mitad y la paso a activos duros", 2],
      ["c", "Vendo todo y voy a activos duros", 3],
      ["d", "Vendo todo, voy a activos duros y me endeudo para comprar más", 4],
      ["x", "No lo entiendo / no estoy seguro", 1],
    ],
  },
  {
    id: "q8", orig: 14, factor: "F1",
    text: "Dados el mejor y el peor caso de estas inversiones, ¿cuál preferís?",
    options: [
      ["a", "+USD 200 en el mejor caso; USD 0 en el peor", 1],
      ["b", "+USD 800 en el mejor caso; −USD 200 en el peor", 2],
      ["c", "+USD 2.600 en el mejor caso; −USD 800 en el peor", 3],
      ["d", "+USD 4.800 en el mejor caso; −USD 2.400 en el peor", 4],
      ["x", "No lo entiendo / no estoy seguro", 1],
    ],
  },
  {
    id: "q9", orig: 16, factor: "F3",
    text: "Escenario de GANANCIA: te dan USD 1.000. ¿Qué preferís hacer con esa ganancia?",
    options: [
      ["a", "Asegurar +USD 500 (ganancia garantizada)", 1],
      ["b", "Jugártela: 50% de ganar +USD 1.000, 50% de no ganar nada", 3],
    ],
  },
  {
    id: "q10", orig: 17, factor: "F3",
    text: "Escenario de PÉRDIDA (es el mismo de antes, al revés): te dan USD 2.000 pero vas a perder. ¿Qué preferís?",
    options: [
      ["a", "Asegurar −USD 500 (pérdida garantizada, sabés cuánto perdés)", 1],
      ["b", "Jugártela: 50% de perder −USD 1.000, 50% de no perder nada", 3],
    ],
  },
  {
    id: "q11", orig: 18, factor: "F1",
    text: "Heredás USD 100.000 con la condición de invertir TODO en UNA sola opción. ¿Cuál elegís?",
    options: [
      ["a", "Caja de ahorro o money market", 1],
      ["b", "Un fondo que tiene acciones y bonos", 2],
      ["c", "Una cartera de 15 acciones", 3],
      ["d", "Commodities (oro, plata, petróleo)", 4],
      ["x", "No lo entiendo / no estoy seguro", 1],
    ],
  },
  {
    id: "q12", orig: 19, factor: "F1",
    text: "Si tuvieras que invertir USD 20.000, ¿qué mezcla te resulta más atractiva?",
    options: [
      ["a", "60% bajo riesgo, 30% medio, 10% alto", 1],
      ["b", "30% bajo riesgo, 40% medio, 30% alto", 2],
      ["c", "10% bajo riesgo, 40% medio, 50% alto", 3],
      ["x", "No lo entiendo / no estoy seguro", 1],
    ],
  },
  {
    id: "q13", orig: 20, factor: "F2",
    text: "Un amigo geólogo arma un grupo para financiar una mina de oro exploratoria: paga 50 a 100 veces si sale bien, vale cero si fracasa. La chance de éxito es 20%. ¿Cuánto invertirías?",
    options: [
      ["a", "Nada", 1],
      ["b", "Un mes de sueldo", 2],
      ["c", "Tres meses de sueldo", 3],
      ["d", "Seis meses de sueldo", 4],
      ["x", "No lo entiendo / no estoy seguro", 1],
    ],
  },
];

const RAW_MIN = 13;
const RAW_MAX = 47;

// Normas poblacionales de Kuzniak et al. (2015), n = 160.279.
const NORM_MEAN = 27.53;
const NORM_SD = 5.48;

// ── scoring (espejo de grable_lytton.py) ───────────────────────────────────

// Ítem sin responder o inválido puntúa el mínimo (1): un cuestionario
// incompleto tiende a conservador, nunca infla el perfil.
function scoreRaw(answers) {
  let total = 0;
  for (const item of GL_ITEMS) {
    const letter = answers[item.id];
    const opt = item.options.find(o => o[0] === letter);
    total += opt ? opt[2] : 1;
  }
  return total;
}

function rawToTolerance1to10(raw) {
  if (raw <= RAW_MIN) return 1.0;
  if (raw >= RAW_MAX) return 10.0;
  return Math.round((1.0 + ((raw - RAW_MIN) / (RAW_MAX - RAW_MIN)) * 9.0) * 10) / 10;
}

function riskLevelLabel(raw) {
  if (raw >= 33) return { key: "high",          es: "Tolerancia alta",       pill: "pill-red" };
  if (raw >= 29) return { key: "above-average", es: "Por encima del promedio", pill: "pill-orange" };
  if (raw >= 23) return { key: "average",       es: "Promedio",              pill: "pill-blue" };
  if (raw >= 19) return { key: "below-average", es: "Por debajo del promedio", pill: "pill-green" };
  return { key: "low", es: "Tolerancia baja", pill: "pill-grey" };
}

// Puntaje por factor: sumado y expresado como % del máximo de ese factor,
// única forma de comparar factores de distinta cantidad de ítems.
function scoreByFactor(answers) {
  const out = {};
  for (const key of Object.keys(GL_FACTORS)) {
    out[key] = { raw: 0, min: 0, max: 0, items: 0 };
  }
  for (const item of GL_ITEMS) {
    const f = out[item.factor];
    const opt = item.options.find(o => o[0] === answers[item.id]);
    const pts = item.options.map(o => o[2]);
    f.raw += opt ? opt[2] : 1;
    f.min += Math.min(...pts);
    f.max += Math.max(...pts);
    f.items += 1;
  }
  for (const key of Object.keys(out)) {
    const f = out[key];
    f.pct = f.max === f.min ? 0 : Math.round(((f.raw - f.min) / (f.max - f.min)) * 100);
  }
  return out;
}

// ── estado + render ────────────────────────────────────────────────────────

const answers = {};
let showPoints = false;

function q(id) { return document.getElementById(id); }

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderItems() {
  const host = q("gl-items");
  host.innerHTML = GL_ITEMS.map((item, i) => {
    const f = GL_FACTORS[item.factor];
    const opts = item.options.map(([letter, text, pts]) => `
      <label class="gl-option" data-q="${item.id}" data-letter="${letter}">
        <input type="radio" name="${item.id}" value="${letter}">
        <span class="gl-option-text">${esc(text)}</span>
        <span class="gl-points ${showPoints ? "" : "hidden"}">${pts}</span>
      </label>`).join("");
    return `
      <div class="gl-question" id="card-${item.id}">
        <div class="gl-q-head">
          <span class="gl-q-num">${i + 1}</span>
          <div class="gl-q-text">${esc(item.text)}</div>
        </div>
        <div class="gl-q-meta">
          <span class="pill ${f.pill}">${f.label}</span>
          <span class="gl-orig">ítem ${item.orig} del paper</span>
        </div>
        <div class="gl-options">${opts}</div>
      </div>`;
  }).join("");

  host.querySelectorAll("input[type=radio]").forEach(input => {
    input.addEventListener("change", () => {
      answers[input.name] = input.value;
      const card = q("card-" + input.name);
      card.classList.add("is-answered");
      card.querySelectorAll(".gl-option").forEach(l => l.classList.remove("is-picked"));
      input.closest(".gl-option").classList.add("is-picked");
      updateProgress();
    });
  });
}

function updateProgress() {
  const done = Object.keys(answers).length;
  const pct = Math.round((done / GL_ITEMS.length) * 100);
  q("gl-progress-fill").style.width = pct + "%";
  q("gl-progress-label").textContent = `${done} de ${GL_ITEMS.length} respondidas`;
  q("gl-submit").disabled = done < GL_ITEMS.length;
  q("gl-submit").textContent = done < GL_ITEMS.length
    ? `Faltan ${GL_ITEMS.length - done} respuestas`
    : "Calcular mi puntaje";
}

// Posición relativa contra la norma poblacional de 2015 (z → percentil
// aproximado con la CDF normal; Abramowitz & Stegun 26.2.17).
function percentileFromZ(z) {
  const p = 0.2316419, b = [0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429];
  const az = Math.abs(z);
  const t = 1 / (1 + p * az);
  const poly = b[0] * t + b[1] * t ** 2 + b[2] * t ** 3 + b[3] * t ** 4 + b[4] * t ** 5;
  const cdf = 1 - (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-az * az / 2) * poly;
  return z >= 0 ? cdf : 1 - cdf;
}

function renderResult() {
  const raw = scoreRaw(answers);
  const tol = rawToTolerance1to10(raw);
  const level = riskLevelLabel(raw);
  const factors = scoreByFactor(answers);
  const z = (raw - NORM_MEAN) / NORM_SD;
  const pct = Math.round(percentileFromZ(z) * 100);
  // La escala dibuja 35 celdas discretas (13…47, una por puntaje posible), no 34
  // intervalos: el marcador va al CENTRO de su celda. Así siempre cae dentro de
  // la banda de color que le corresponde y la burbuja no se sale en los extremos.
  const cells = RAW_MAX - RAW_MIN + 1;
  const posPct = ((raw - RAW_MIN) + 0.5) / cells * 100;

  q("gl-result").innerHTML = `
    <div class="card card-hero" style="margin-top:0;">
      <div class="card-header">
        <div>
          <h2>Resultado del test</h2>
          <div class="subtitle">Escala Grable-Lytton · 13 ítems · suma simple de puntajes</div>
        </div>
        <div class="pill-cluster"><span class="pill ${level.pill}">${level.es}</span></div>
      </div>
      <div class="card-body">

        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Puntaje bruto</div>
            <div class="kpi-value">${raw}<span style="font-size:16px;color:var(--rf-text-faint);"> / 47</span></div>
            <div class="kpi-sub">Rango posible ${RAW_MIN}–${RAW_MAX}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Categoría oficial</div>
            <div class="kpi-value" style="font-size:22px;">${level.es}</div>
            <div class="kpi-sub">Cortes de la escala publicada</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Tolerancia del motor</div>
            <div class="kpi-value">${tol.toFixed(1)}<span style="font-size:16px;color:var(--rf-text-faint);"> / 10</span></div>
            <div class="kpi-sub">Reescalado lineal de 13–47</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Frente a la población</div>
            <div class="kpi-value">p${pct}</div>
            <div class="kpi-sub">z = ${z >= 0 ? "+" : ""}${z.toFixed(2)} vs. media 27,53</div>
          </div>
        </div>

        <div class="gl-scale-wrap">
          <div class="gl-scale-title">Dónde cae tu puntaje en la escala</div>
          <div class="gl-scale">
            <div class="gl-scale-band gl-band-1"><span>baja</span></div>
            <div class="gl-scale-band gl-band-2"><span>bajo prom.</span></div>
            <div class="gl-scale-band gl-band-3"><span>promedio</span></div>
            <div class="gl-scale-band gl-band-4"><span>sobre prom.</span></div>
            <div class="gl-scale-band gl-band-5"><span>alta</span></div>
            <div class="gl-scale-marker" style="left:${posPct}%;">
              <div class="gl-scale-bubble">${raw}</div>
            </div>
          </div>
          <!-- Los flex de cada celda replican los de las bandas para que cada
               número caiga exactamente donde cambia el color. -->
          <div class="gl-scale-axis">
            <span style="flex:6">13</span>
            <span style="flex:4">19</span>
            <span style="flex:6">23</span>
            <span style="flex:4">29</span>
            <span style="flex:15">33</span>
            <span class="gl-axis-end">47</span>
          </div>
        </div>

        <div class="section-label">Desagregado por factor</div>
        <p class="fine-print" style="margin-top:0;">
          Los tres factores salen del análisis factorial de 1999. Se muestran para explicar la estructura
          del instrumento: los autores aclaran que <strong>no son subescalas válidas por separado</strong>
          (sus alfas son bajos). El único puntaje interpretable es el total de arriba.
        </p>
        ${Object.entries(factors).map(([key, f]) => {
          const meta = GL_FACTORS[key];
          return `
          <div class="gl-factor-row">
            <div class="gl-factor-name">
              <span class="pill ${meta.pill}">${meta.label}</span>
              <span class="gl-factor-sub">${f.items} ítems · α = ${meta.alpha}</span>
            </div>
            <div class="weight-bar-track" style="flex:1;">
              <div class="weight-bar-fill" style="width:${f.pct}%;"></div>
            </div>
            <div class="gl-factor-val">${f.raw}<span style="color:var(--rf-text-faint);">/${f.max}</span></div>
          </div>`;
        }).join("")}

        <div class="section-label">Detalle respuesta por respuesta</div>
        <div class="tbl-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Ítem del paper</th><th>Factor</th><th>Tu respuesta</th><th style="text-align:right;">Puntos</th></tr>
            </thead>
            <tbody>
              ${GL_ITEMS.map((item, i) => {
                const opt = item.options.find(o => o[0] === answers[item.id]);
                return `<tr>
                  <td class="mono">${i + 1}</td>
                  <td class="mono">${item.orig}</td>
                  <td>${GL_FACTORS[item.factor].label}</td>
                  <td>${esc(opt ? opt[1] : "—")}</td>
                  <td style="text-align:right;" class="mono"><strong>${opt ? opt[2] : 1}</strong></td>
                </tr>`;
              }).join("")}
              <tr style="background:var(--rf-bg-soft);">
                <td colspan="4"><strong>Total</strong></td>
                <td style="text-align:right;" class="mono"><strong>${raw}</strong></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="ai-disclaimer" style="margin-top:20px;">
          <strong>Qué mide y qué no.</strong>
          Este puntaje es <em>tolerancia declarada</em> (willingness): cuánto riesgo decís estar dispuesto
          a asumir frente a escenarios hipotéticos, sin plata real en juego. No mide:
          <ul>
            <li>tu <strong>capacidad financiera</strong> de absorber una pérdida — eso sale del KYC (patrimonio, ingresos, horizonte, dependientes);</li>
            <li>tu <strong>reacción real</strong> ante una caída — declarar que aguantarías un −30% y aguantarlo son cosas distintas;</li>
            <li>ningún <strong>perfil de inversor</strong> por sí solo: el perfil sale de cruzar esto con capacidad, horizonte y objetivo, y lo aprueba un asesor.</li>
          </ul>
        </div>

        <div class="actions" style="margin-top:18px;">
          <button class="btn-secondary" id="gl-copy">Copiar resultado</button>
          <button class="btn-secondary" id="gl-reset">Volver a empezar</button>
        </div>
      </div>
    </div>`;

  q("gl-copy").addEventListener("click", () => {
    const linea = GL_ITEMS.map(it => `${it.id}=${answers[it.id]}`).join(" ");
    const texto =
      `Test de inversor — escala Grable-Lytton (1999)\n` +
      `Puntaje bruto: ${raw}/47 (${level.es})\n` +
      `Tolerancia 1-10: ${tol.toFixed(1)}\n` +
      `Percentil vs. norma 2015 (media 27,53 / SD 5,48): p${pct}\n` +
      `Respuestas: ${linea}`;
    navigator.clipboard.writeText(texto).then(() => {
      q("gl-copy").textContent = "¡Copiado!";
      setTimeout(() => { q("gl-copy").textContent = "Copiar resultado"; }, 1800);
    }).catch(() => {
      q("gl-copy").textContent = "No se pudo copiar";
    });
  });

  q("gl-reset").addEventListener("click", () => {
    for (const k of Object.keys(answers)) delete answers[k];
    q("gl-result").innerHTML = "";
    q("gl-form-card").classList.remove("hidden");
    renderItems();
    updateProgress();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  q("gl-form-card").classList.add("hidden");
  q("gl-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── init ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  renderItems();
  updateProgress();

  q("gl-submit").addEventListener("click", renderResult);

  q("gl-toggle-points").addEventListener("click", () => {
    showPoints = !showPoints;
    q("gl-toggle-points").textContent = showPoints
      ? "Ocultar puntajes"
      : "Mostrar puntajes de cada opción";
    document.querySelectorAll(".gl-points").forEach(el => el.classList.toggle("hidden", !showPoints));
  });
});
