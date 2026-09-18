/* Piezas Planas — UI (pywebview)
 * callApi() como puente único hacia window.pywebview.api, resultados con
 * forma {ok, error?} — misma convención de PipeMirror/AGP_LAUNCHER.
 */

function callApi(method, ...args) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[method]) {
    return Promise.resolve(window.pywebview.api[method](...args));
  }
  return Promise.resolve(null);
}

// ── Titlebar (frameless, arrastre vía clase pywebview-drag-region) ──────

document.getElementById("btn-min").addEventListener("click", () => callApi("minimize"));
document.getElementById("btn-close").addEventListener("click", () => callApi("close_app"));

// ── Glow de cursor ───────────────────────────────────────────────────

document.addEventListener("mousemove", (ev) => {
  const glow = document.getElementById("glow-layer");
  glow.style.setProperty("--mx", (ev.clientX / innerWidth) * 100 + "%");
  glow.style.setProperty("--my", (ev.clientY / innerHeight) * 100 + "%");
});

// ── Canvas: partículas con gravedad (fondo ambiental) ────────────────

const bgCanvas = document.getElementById("bg-canvas");
const bctx = bgCanvas.getContext("2d");
function resizeBg() { bgCanvas.width = innerWidth; bgCanvas.height = innerHeight; }
resizeBg();
addEventListener("resize", resizeBg);

const GRAVEDAD = 0.1;
const AMORTIGUACION = 0.6;
const FRICCION = 0.995;
const particulas = [];

function nuevaParticula() {
  return {
    x: Math.random() * bgCanvas.width,
    y: -Math.random() * 200,
    vx: (Math.random() - 0.5) * 0.5,
    vy: 0,
    r: 1.4 + Math.random() * 2,
    color: Math.random() < 0.5 ? "46,134,193" : "100,116,139",
  };
}
for (let i = 0; i < 55; i++) particulas.push(nuevaParticula());

function stepGravedad() {
  bctx.clearRect(0, 0, bgCanvas.width, bgCanvas.height);
  for (const p of particulas) {
    p.vy += GRAVEDAD;
    p.vx *= FRICCION;
    p.x += p.vx;
    p.y += p.vy;
    if (p.y > bgCanvas.height - p.r) {
      p.y = bgCanvas.height - p.r;
      p.vy *= -AMORTIGUACION;
      p.vx += (Math.random() - 0.5) * 0.3;
      if (Math.abs(p.vy) < 0.6) Object.assign(p, nuevaParticula());
    }
    if (p.x < 0 || p.x > bgCanvas.width) p.vx *= -1;
    bctx.beginPath();
    bctx.fillStyle = `rgba(${p.color},0.45)`;
    bctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    bctx.fill();
  }
  requestAnimationFrame(stepGravedad);
}
requestAnimationFrame(stepGravedad);

// ── Canvas: impacto / shockwave (solo en acciones principales) ───────

const impactCanvas = document.getElementById("impact-canvas");
const ictx = impactCanvas.getContext("2d");
function resizeImpact() { impactCanvas.width = innerWidth; impactCanvas.height = innerHeight; }
resizeImpact();
addEventListener("resize", resizeImpact);

function impact(cx, cy, colorRGB) {
  colorRGB = colorRGB || "46,134,193";
  impactCanvas.classList.remove("hide");
  ictx.clearRect(0, 0, impactCanvas.width, impactCanvas.height);
  dibujarEstallido(cx, cy, colorRGB);
  animarOnda(cx, cy, colorRGB);
  setTimeout(() => {
    impactCanvas.classList.add("hide");
    setTimeout(() => ictx.clearRect(0, 0, impactCanvas.width, impactCanvas.height), 500);
  }, 750);
}

function dibujarEstallido(cx, cy, colorRGB) {
  const flash = ictx.createRadialGradient(cx, cy, 0, cx, cy, 40);
  flash.addColorStop(0, `rgba(${colorRGB},0.85)`);
  flash.addColorStop(1, `rgba(${colorRGB},0)`);
  ictx.fillStyle = flash;
  ictx.fillRect(cx - 44, cy - 44, 88, 88);
  const rayos = 7 + Math.floor(Math.random() * 4);
  for (let i = 0; i < rayos; i++) {
    const angulo = (i / rayos) * Math.PI * 2 + (Math.random() - 0.5) * 0.4;
    dibujarRayo(cx, cy, angulo, colorRGB, 5, 1);
  }
}
function dibujarRayo(x, y, angulo, colorRGB, segmentos, profundidad) {
  let cx = x, cy = y, a = angulo;
  ictx.strokeStyle = `rgba(${colorRGB},${0.8 / profundidad})`;
  ictx.lineWidth = Math.max(0.6, 2.2 / profundidad);
  ictx.beginPath();
  ictx.moveTo(cx, cy);
  for (let s = 0; s < segmentos; s++) {
    const len = (22 - s * 2 + Math.random() * 10) / profundidad;
    a += (Math.random() - 0.5) * 0.7;
    cx += Math.cos(a) * len;
    cy += Math.sin(a) * len;
    ictx.lineTo(cx, cy);
  }
  ictx.stroke();
}
function animarOnda(cx, cy, colorRGB) {
  const inicio = performance.now();
  const duracion = 460;
  function frame(now) {
    const t = Math.min(1, (now - inicio) / duracion);
    ictx.save();
    ictx.globalAlpha = 1 - t;
    ictx.strokeStyle = `rgba(${colorRGB},0.5)`;
    ictx.lineWidth = 2;
    ictx.beginPath();
    ictx.arc(cx, cy, 8 + t * 60, 0, Math.PI * 2);
    ictx.stroke();
    ictx.restore();
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}
function impactAt(el, colorRGB) {
  const r = el.getBoundingClientRect();
  impact(r.left + r.width / 2, r.top + r.height / 2, colorRGB);
}

// ── Estado del wizard ─────────────────────────────────────────────────

const STEP_ORDER = ["file", "tecoflex", "tamano", "datos", "tabla", "accesorio"];

const state = {
  documento: null,
  tieneTecoflex: null,
  piezaGrande: null,
  modoAccesorio: null,   // "PC" | "AL" | null
  cantidadPc: 1,
  cantidadLites: 1,
  nombreGeneral: "",
  carpetaDestino: "",
  lites: [],
  tiposCristal: [],
  espesoresCache: {},
};

let currentStep = null;

function resetState() {
  state.documento = null;
  state.tieneTecoflex = null;
  state.piezaGrande = null;
  state.modoAccesorio = null;
  state.cantidadPc = 1;
  state.cantidadLites = 1;
  state.nombreGeneral = "";
  state.carpetaDestino = "";
  state.lites = [];
  document.getElementById("in-cantidad").value = 1;
  document.getElementById("in-nombre").value = "";
  document.getElementById("in-cantidad-pc").value = 1;
  document.getElementById("folder-box").classList.remove("chosen");
  document.getElementById("folder-text").textContent = "Sin carpeta seleccionada";
  document.getElementById("btn-datos-next").disabled = false;
  document.querySelectorAll("#btn-tamano-grande, #btn-tamano-pequena, #btn-accesorio-pc, #btn-accesorio-al")
    .forEach((b) => b.classList.remove("selected"));
  document.getElementById("accesorio-pc-cantidad").classList.add("hide");
  document.getElementById("accesorio-al-bloqueado").classList.add("hide");
  document.getElementById("btn-procesar").disabled = true;
}

// ── Navegación entre pasos ───────────────────────────────────────────

function goStep(name, direction) {
  direction = direction || (STEP_ORDER.indexOf(name) >= STEP_ORDER.indexOf(currentStep) ? "fwd" : "back");
  const viewport = document.getElementById("step-viewport");
  const sections = document.querySelectorAll(".step");
  sections.forEach((sec) => {
    sec.classList.remove("step-active", "enter-fwd", "enter-back");
  });
  const target = document.querySelector(`.step[data-step="${name}"]`);
  target.classList.add("step-active", direction === "fwd" ? "enter-fwd" : "enter-back");
  const wide = target.classList.contains("step-wide");
  viewport.classList.toggle("viewport-wide", wide);
  document.getElementById("btn-back").classList.toggle("wide", wide);
  currentStep = name;
  updateStepper(name);
  updateBackButton(name);
}

function updateStepper(name) {
  const stepper = document.getElementById("stepper");
  const idx = STEP_ORDER.indexOf(name);
  if (idx === -1) {
    stepper.style.opacity = "0.35";
  } else {
    stepper.style.opacity = "1";
  }
  document.querySelectorAll(".step-dot").forEach((dot) => {
    const dotIdx = STEP_ORDER.indexOf(dot.dataset.dot);
    dot.classList.toggle("active", dotIdx === idx);
    dot.classList.toggle("done", idx !== -1 && dotIdx < idx);
  });
  document.querySelectorAll(".step-line").forEach((line, i) => {
    line.classList.toggle("done", idx !== -1 && i < idx);
  });
}

function updateBackButton(name) {
  const btn = document.getElementById("btn-back");
  const hideOn = ["file", "procesando", "resultado"];
  btn.classList.toggle("hide", hideOn.includes(name));
}

document.getElementById("btn-back").addEventListener("click", () => {
  const idx = STEP_ORDER.indexOf(currentStep);
  if (idx > 0) goStep(STEP_ORDER[idx - 1], "back");
});

// ── Splash ────────────────────────────────────────────────────────────

function skipSplash() {
  const splash = document.getElementById("splash");
  if (splash.classList.contains("splash-out")) return;
  splash.classList.add("splash-out");
  setTimeout(() => {
    splash.classList.add("hide");
    const wizard = document.getElementById("wizard");
    wizard.classList.remove("hide");
    wizard.classList.add("wizard-in");
    goStep("file", "fwd");
    refreshDocs();
  }, 480);
}
document.getElementById("splash").addEventListener("click", skipSplash);
setTimeout(skipSplash, 2600);

// ── Paso: archivo ─────────────────────────────────────────────────────

let docsSeleccionado = null;

async function refreshDocs() {
  const list = document.getElementById("doc-list");
  const btnNext = document.getElementById("btn-file-next");
  list.innerHTML = `<div class="doc-empty">Buscando documentos abiertos…</div>`;
  btnNext.disabled = true;

  const r = await callApi("listar_documentos");
  if (!r || !r.ok) {
    list.innerHTML = `<div class="doc-empty">No se pudo consultar AutoCAD${r && r.error ? ": " + r.error : ""}.</div>`;
    return;
  }
  if (!r.documentos.length) {
    list.innerHTML = `<div class="doc-empty">No se encontró ningún DWG abierto en AutoCAD.<br/>Abre el archivo en AutoCAD e intenta de nuevo.</div>`;
    return;
  }
  list.innerHTML = "";
  r.documentos.forEach((doc) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "doc-card";
    if (doc.guardado === false) el.classList.add("doc-card-disabled");
    el.innerHTML = `
      <span class="doc-card-icon">&#128196;</span>
      <span class="doc-card-body">
        <div class="doc-card-name"></div>
        <div class="doc-card-path"></div>
      </span>
      <span class="doc-card-check">&#10003;</span>`;
    el.querySelector(".doc-card-name").textContent = doc.name;
    if (doc.guardado === false) {
      el.querySelector(".doc-card-path").textContent =
        "⚠ Este dibujo no se ha guardado en disco todavía — guárdalo en AutoCAD (Ctrl+S) primero.";
      el.disabled = true;
      list.appendChild(el);
      return;
    }
    el.querySelector(".doc-card-path").textContent = doc.path;
    el.addEventListener("click", () => {
      docsSeleccionado = doc;
      state.documento = doc;
      list.querySelectorAll(".doc-card").forEach((c) => c.classList.remove("selected"));
      el.classList.add("selected");
      btnNext.disabled = false;
    });
    list.appendChild(el);
  });
}

document.getElementById("btn-refresh-docs").addEventListener("click", refreshDocs);
document.getElementById("btn-file-next").addEventListener("click", (ev) => {
  if (!state.documento) return;
  impactAt(ev.currentTarget, "46,134,193");
  goStep("tecoflex", "fwd");
});

// ── Paso: tecoflex ────────────────────────────────────────────────────

document.getElementById("btn-teco-si").addEventListener("click", (ev) => {
  state.tieneTecoflex = true;
  impactAt(ev.currentTarget, "30,142,62");
  goStep("tamano", "fwd");
});
document.getElementById("btn-teco-no").addEventListener("click", (ev) => {
  state.tieneTecoflex = false;
  impactAt(ev.currentTarget, "100,116,139");
  goStep("tamano", "fwd");
});

// ── Paso: tamaño (global, aplica a todos los lites y a la TAPA) ──────

document.getElementById("btn-tamano-grande").addEventListener("click", (ev) => {
  state.piezaGrande = true;
  impactAt(ev.currentTarget, "30,142,62");
  goStep("datos", "fwd");
});
document.getElementById("btn-tamano-pequena").addEventListener("click", (ev) => {
  state.piezaGrande = false;
  impactAt(ev.currentTarget, "100,116,139");
  goStep("datos", "fwd");
});

// ── Paso: datos generales ─────────────────────────────────────────────

document.getElementById("btn-elegir-carpeta").addEventListener("click", async () => {
  const r = await callApi("elegir_carpeta");
  if (r && r.ok && r.carpeta) {
    state.carpetaDestino = r.carpeta;
    const box = document.getElementById("folder-box");
    box.classList.add("chosen");
    document.getElementById("folder-text").textContent = r.carpeta;
  }
});

document.getElementById("btn-datos-next").addEventListener("click", (ev) => {
  const cantidadInput = document.getElementById("in-cantidad");
  const nombreInput = document.getElementById("in-nombre");
  const cantidad = parseInt(cantidadInput.value, 10);
  const nombre = nombreInput.value.trim();

  if (!Number.isInteger(cantidad) || cantidad < 1) {
    cantidadInput.focus();
    impactAt(ev.currentTarget, "217,48,37");
    return;
  }
  if (!nombre) {
    nombreInput.focus();
    impactAt(ev.currentTarget, "217,48,37");
    return;
  }
  if (!state.carpetaDestino) {
    impactAt(document.getElementById("btn-elegir-carpeta"), "217,48,37");
    return;
  }

  state.cantidadLites = cantidad;
  state.nombreGeneral = nombre;
  construirLites(cantidad);
  impactAt(ev.currentTarget, "46,134,193");
  goStep("tabla", "fwd");
});

// ── Paso: tabla de lites ──────────────────────────────────────────────

function construirLites(cantidad) {
  state.lites = [];
  for (let i = 0; i < cantidad; i++) {
    state.lites.push({
      posicion: (i + 1) * 100,
      tipo_cristal: "",
      espesor: "",
      pintura: false,
      caja: false,
      compensacion: { estado: "pending" }, // pending | ok | error
    });
  }
  renderTablaLites();
}

async function cargarTiposCristalSiHaceFalta() {
  if (state.tiposCristal.length) return state.tiposCristal;
  const r = await callApi("tipos_cristal");
  state.tiposCristal = Array.isArray(r) ? r : [];
  return state.tiposCristal;
}

async function renderTablaLites() {
  const tbody = document.getElementById("tabla-lites-body");
  tbody.innerHTML = "";
  const tipos = await cargarTiposCristalSiHaceFalta();

  state.lites.forEach((lite, idx) => {
    const tr = document.createElement("tr");
    tr.dataset.idx = idx;

    const tipoOptions = `<option value="">Elegir…</option>` +
      tipos.map((t) => `<option value="${t.id}">${t.label}</option>`).join("");

    tr.innerHTML = `
      <td class="pos-cell">${lite.posicion}</td>
      <td><select class="sel-tipo">${tipoOptions}</select></td>
      <td><select class="sel-espesor" disabled><option value="">—</option></select></td>
      <td><label class="toggle"><input type="checkbox" class="chk-pintura" /><span class="toggle-slider"></span></label></td>
      <td><label class="toggle"><input type="checkbox" class="chk-caja" /><span class="toggle-slider"></span></label></td>
      <td class="comp-cell comp-pending">—</td>
    `;
    tbody.appendChild(tr);

    const selTipo = tr.querySelector(".sel-tipo");
    const selEspesor = tr.querySelector(".sel-espesor");
    const chkPintura = tr.querySelector(".chk-pintura");
    const chkCaja = tr.querySelector(".chk-caja");

    selTipo.addEventListener("change", async () => {
      lite.tipo_cristal = selTipo.value;
      lite.espesor = "";
      lite.pintura = false;
      lite.caja = false;
      chkPintura.checked = false;
      chkCaja.checked = false;

      if (lite.tipo_cristal === "OTROS") {
        // "Otros" no usa espesor/pintura/caja: siempre 2.5mm hacia afuera.
        selEspesor.innerHTML = `<option value="">No aplica</option>`;
        selEspesor.disabled = true;
        chkPintura.disabled = true;
        chkCaja.disabled = true;
        lite.espesor = 0; // dummy: el backend lo ignora para OTROS
        recalcularFila(lite, tr);
        return;
      }

      chkPintura.disabled = false;
      chkCaja.disabled = false;
      await poblarEspesores(lite, selEspesor);
      recalcularFila(lite, tr);
    });

    selEspesor.addEventListener("change", () => {
      lite.espesor = selEspesor.value ? parseFloat(selEspesor.value) : "";
      recalcularFila(lite, tr);
    });

    chkPintura.addEventListener("change", () => { lite.pintura = chkPintura.checked; recalcularFila(lite, tr); });
    chkCaja.addEventListener("change", () => { lite.caja = chkCaja.checked; recalcularFila(lite, tr); });
  });

  actualizarBotonProcesar();
}

async function poblarEspesores(lite, selEspesor) {
  selEspesor.innerHTML = `<option value="">Cargando…</option>`;
  selEspesor.disabled = true;
  if (!lite.tipo_cristal) {
    selEspesor.innerHTML = `<option value="">—</option>`;
    return;
  }
  let espesores = state.espesoresCache[lite.tipo_cristal];
  if (!espesores) {
    const r = await callApi("espesores_validos", lite.tipo_cristal);
    espesores = (r && r.ok) ? r.espesores : [];
    state.espesoresCache[lite.tipo_cristal] = espesores;
  }
  selEspesor.innerHTML = `<option value="">Elegir…</option>` +
    espesores.map((e) => `<option value="${e}">${e} mm</option>`).join("");
  selEspesor.disabled = false;
}

async function recalcularFila(lite, tr) {
  const celda = tr.querySelector(".comp-cell");

  if (!lite.tipo_cristal || lite.espesor === "" || lite.espesor === undefined) {
    lite.compensacion = { estado: "pending" };
    celda.className = "comp-cell comp-pending";
    celda.textContent = "Elige tipo y espesor…";
    actualizarBotonProcesar();
    return;
  }

  celda.className = "comp-cell comp-pending";
  celda.textContent = "Calculando…";

  const r = await callApi(
    "calcular_compensacion",
    lite.tipo_cristal, lite.espesor, lite.pintura, lite.caja, !!state.piezaGrande
  );

  if (!r || !r.ok) {
    lite.compensacion = { estado: "error", error: (r && r.error) || "Error calculando la compensación." };
    celda.className = "comp-cell comp-error";
    celda.textContent = lite.compensacion.error;
  } else if (r.aplica) {
    lite.compensacion = { estado: "ok", valor: r.valor, aplica: true };
    celda.className = "comp-cell comp-ok";
    celda.textContent = `${r.valor} mm`;
  } else {
    lite.compensacion = { estado: "ok", valor: r.valor, aplica: false };
    celda.className = "comp-cell comp-na";
    celda.textContent = "Sin compensación (matado de filos)";
  }
  actualizarBotonProcesar();
}

function actualizarBotonProcesar() {
  const btn = document.getElementById("btn-tabla-next");
  const todasOk = state.lites.length > 0 && state.lites.every((l) => l.compensacion && l.compensacion.estado === "ok");
  btn.disabled = !todasOk;
}

document.getElementById("btn-tabla-next").addEventListener("click", (ev) => {
  impactAt(ev.currentTarget, "46,134,193");
  prepararPasoAccesorio();
  goStep("accesorio", "fwd");
});

// ── Paso: PC / AL ─────────────────────────────────────────────────────

function prepararPasoAccesorio() {
  const btnAl = document.getElementById("btn-accesorio-al");
  const avisoBloqueado = document.getElementById("accesorio-al-bloqueado");
  const alDisponible = !!state.tieneTecoflex;

  btnAl.classList.toggle("choice-disabled", !alDisponible);
  avisoBloqueado.classList.toggle("hide", alDisponible);

  // Si AL había quedado elegido y ahora no aplica (el usuario se devolvió
  // y cambió tecoflex a "No"), se resetea la elección.
  if (!alDisponible && state.modoAccesorio === "AL") {
    state.modoAccesorio = null;
    document.getElementById("accesorio-pc-cantidad").classList.add("hide");
    document.querySelectorAll("#btn-accesorio-pc, #btn-accesorio-al").forEach((b) => b.classList.remove("selected"));
  }
  actualizarBotonAccesorio();
}

function actualizarBotonAccesorio() {
  const btn = document.getElementById("btn-procesar");
  if (state.modoAccesorio === "PC") {
    btn.disabled = !(Number.isInteger(state.cantidadPc) && state.cantidadPc >= 1);
  } else if (state.modoAccesorio === "AL") {
    btn.disabled = !state.tieneTecoflex;
  } else {
    btn.disabled = true;
  }
}

document.getElementById("btn-accesorio-pc").addEventListener("click", (ev) => {
  state.modoAccesorio = "PC";
  document.querySelectorAll("#btn-accesorio-pc, #btn-accesorio-al").forEach((b) => b.classList.remove("selected"));
  ev.currentTarget.classList.add("selected");
  document.getElementById("accesorio-pc-cantidad").classList.remove("hide");
  impactAt(ev.currentTarget, "46,134,193");
  actualizarBotonAccesorio();
});

document.getElementById("btn-accesorio-al").addEventListener("click", (ev) => {
  if (!state.tieneTecoflex) {
    impactAt(ev.currentTarget, "217,48,37");
    return;
  }
  state.modoAccesorio = "AL";
  document.querySelectorAll("#btn-accesorio-pc, #btn-accesorio-al").forEach((b) => b.classList.remove("selected"));
  ev.currentTarget.classList.add("selected");
  document.getElementById("accesorio-pc-cantidad").classList.add("hide");
  impactAt(ev.currentTarget, "46,134,193");
  actualizarBotonAccesorio();
});

document.getElementById("in-cantidad-pc").addEventListener("input", (ev) => {
  const v = parseInt(ev.currentTarget.value, 10);
  state.cantidadPc = Number.isInteger(v) ? v : NaN;
  actualizarBotonAccesorio();
});

// ── Procesar ──────────────────────────────────────────────────────────

const FRASES_PROCESANDO = [
  "Conectando con AutoCAD…",
  "Validando el layer PERIMETRO…",
  "Calculando offsets…",
  "Aplicando compensación por lite…",
  "Guardando los archivos…",
];

let cicloProcesando = null;

function iniciarCicloProcesando() {
  const el = document.getElementById("procesando-texto");
  let i = 0;
  el.style.opacity = "1";
  el.textContent = FRASES_PROCESANDO[0];
  cicloProcesando = setInterval(() => {
    i = (i + 1) % FRASES_PROCESANDO.length;
    el.style.opacity = "0";
    setTimeout(() => { el.textContent = FRASES_PROCESANDO[i]; el.style.opacity = "1"; }, 250);
  }, 2200);
}
function detenerCicloProcesando() {
  if (cicloProcesando) clearInterval(cicloProcesando);
  cicloProcesando = null;
}

document.getElementById("btn-procesar").addEventListener("click", async (ev) => {
  impactAt(ev.currentTarget, "46,134,193");
  goStep("procesando", "fwd");
  iniciarCicloProcesando();

  const payload = {
    documento: state.documento,
    tiene_tecoflex: !!state.tieneTecoflex,
    pieza_grande: !!state.piezaGrande,
    modo_accesorio: state.modoAccesorio,
    cantidad_pc: state.modoAccesorio === "PC" ? state.cantidadPc : 0,
    lites: state.lites.map((l) => ({
      posicion: l.posicion,
      tipo_cristal: l.tipo_cristal,
      espesor: l.espesor,
      pintura: l.pintura,
      caja: l.caja,
    })),
    nombre_general: state.nombreGeneral,
    carpeta_destino: state.carpetaDestino,
  };

  const r = await callApi("procesar", payload);
  detenerCicloProcesando();

  if (!r || !r.ok) {
    mostrarResultadoError((r && r.error) || "No se recibió respuesta del proceso.");
  } else {
    mostrarResultadoOk(r);
  }
});

function mostrarResultadoOk(r) {
  document.getElementById("resultado-ok").classList.remove("hide");
  document.getElementById("resultado-error").classList.add("hide");

  document.getElementById("res-main").textContent = nombreArchivo(r.main_output);

  const compRow = document.getElementById("res-comp-row");
  if (r.comparativo_output) {
    compRow.classList.remove("hide");
    document.getElementById("res-comp").textContent = nombreArchivo(r.comparativo_output);
  } else {
    compRow.classList.add("hide");
  }

  const pcRow = document.getElementById("res-pc-row");
  if (r.archivo_pc) {
    pcRow.classList.remove("hide");
    document.getElementById("res-pc").textContent = nombreArchivo(r.archivo_pc);
  } else {
    pcRow.classList.add("hide");
  }

  const tapaRow = document.getElementById("res-tapa-row");
  if (r.archivo_tapa) {
    tapaRow.classList.remove("hide");
    document.getElementById("res-tapa").textContent = nombreArchivo(r.archivo_tapa);
  } else {
    tapaRow.classList.add("hide");
  }

  const litesList = document.getElementById("res-lites-list");
  litesList.innerHTML = "";
  (r.archivos_lites || []).forEach((ruta) => {
    const nombre = nombreArchivo(ruta);
    const match = nombre.match(/_(\d+)\.dwg$/i);
    const pos = match ? match[1] : "?";
    const chip = document.createElement("div");
    chip.className = "res-lite-chip";
    chip.innerHTML = `<span class="chip-pos">${pos}</span><span></span>`;
    chip.querySelector("span:last-child").textContent = nombre;
    litesList.appendChild(chip);
  });
  if (!litesList.children.length) {
    litesList.innerHTML = `<div class="doc-empty">No se generaron archivos individuales por lite.</div>`;
  }

  const detalleBody = document.getElementById("res-detalle-body");
  detalleBody.innerHTML = "";
  (r.detalle || []).forEach((d) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="pos-cell">${d.posicion}</td>
      <td>${d.aplica ? d.compensacion_mm + " mm" : "—"}</td>
      <td>${d.aplica ? "&#10003; Sí" : "Sin compensación"}</td>`;
    detalleBody.appendChild(tr);
  });

  const warnBox = document.getElementById("res-warnings");
  if (r.warnings && r.warnings.length) {
    warnBox.classList.remove("hide");
    warnBox.innerHTML = `<div class="warn-title">&#9888; Avisos</div><ul>${
      r.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")
    }</ul>`;
  } else {
    warnBox.classList.add("hide");
    warnBox.innerHTML = "";
  }

  window._resultadoActual = r;
  goStep("resultado", "fwd");
  setTimeout(() => impact(innerWidth / 2, innerHeight * 0.3, "30,142,62"), 150);
}

function mostrarResultadoError(mensaje) {
  document.getElementById("resultado-ok").classList.add("hide");
  document.getElementById("resultado-error").classList.remove("hide");
  document.getElementById("res-error-msg").textContent = mensaje;
  goStep("resultado", "fwd");
  setTimeout(() => impact(innerWidth / 2, innerHeight * 0.3, "217,48,37"), 150);
}

function nombreArchivo(ruta) {
  if (!ruta) return "";
  return String(ruta).split(/[\\/]/).pop();
}
function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

document.getElementById("btn-abrir-carpeta").addEventListener("click", () => {
  const r = window._resultadoActual;
  if (!r) return;
  const ruta = r.main_output || (r.archivos_lites && r.archivos_lites[0]) || r.comparativo_output || r.archivo_pc || r.archivo_tapa;
  if (ruta) callApi("abrir_carpeta", ruta);
});

document.getElementById("btn-procesar-otro").addEventListener("click", () => {
  resetState();
  goStep("file", "back");
  refreshDocs();
});

document.getElementById("btn-error-volver").addEventListener("click", () => {
  goStep("accesorio", "back");
});
document.getElementById("btn-error-reset").addEventListener("click", () => {
  resetState();
  goStep("file", "back");
  refreshDocs();
});

// ── Easter egg: Pac-Man ────────────────────────────────────────────────
// Se activa escribiendo "pacman" en cualquier momento (mientras la ventana
// tiene foco), salvo que el foco esté en un input/select/textarea real del
// formulario — así no interfiere si alguien usa "pacman" como nombre de
// archivo. Misma técnica de buffer de teclas que el Snake de PipeMirror.

let pacmanBuffer = "";
document.addEventListener("keydown", (ev) => {
  const overlay = document.getElementById("pacman-overlay");
  if (overlay.classList.contains("hide")) {
    const tag = document.activeElement && document.activeElement.tagName;
    const enCampoFormulario = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
    if (!enCampoFormulario) {
      pacmanBuffer = (pacmanBuffer + ev.key).slice(-6).toLowerCase();
      if (pacmanBuffer === "pacman") abrirPacman();
    }
  } else if (ev.key === "Escape") {
    cerrarPacman();
  }
});

function abrirPacman() {
  document.getElementById("pacman-overlay").classList.remove("hide");
  window.PacmanGame.iniciar(
    document.getElementById("pacman-canvas"),
    document.getElementById("pacman-score"),
    document.getElementById("pacman-lives"),
    document.getElementById("pacman-highscore")
  );
}
function cerrarPacman() {
  document.getElementById("pacman-overlay").classList.add("hide");
  window.PacmanGame.detener();
}
document.getElementById("pacman-close").addEventListener("click", cerrarPacman);
