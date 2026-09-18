/* Pac-Man clásico — easter egg de Piezas Planas.
 * Se abre escribiendo "pacman" en cualquier momento (ver app.js, misma
 * técnica del buffer de teclas que usa PipeMirror para "snake") y no
 * interfiere para nada con el wizard normal ni con AutoCAD.
 *
 * Todo en Canvas 2D vanilla, sin librerías — la app corre offline.
 */
window.PacmanGame = (function () {
  const COLS = 19, ROWS = 21, CELL = 24;
  const ALIGN_EPS = 6;
  const DT_MAX = 0.02;

  const rep = (ch, n) => ch.repeat(n);
  const fila = (...partes) => partes.join("");

  // ── Laberinto (simétrico izquierda/derecha) ─────────────────────────
  // '#' pared, '.' pellet, 'o' power pellet, ' ' zona de fantasmas (casa).
  const R_BORDE = rep("#", COLS);
  const R1 = fila("#", "o", rep(".", 15), "o", "#");
  const R2 = fila("#", ".", rep("#", 2), rep(".", 2), rep("#", 2), rep(".", 3), rep("#", 2), rep(".", 2), rep("#", 2), ".", "#");
  const R4 = fila("#", rep(".", 17), "#");
  const R5 = fila(rep("#", 3), rep(".", 5), rep("#", 3), rep(".", 5), rep("#", 3));
  const R8 = fila("#", rep(".", 4), rep("#", 2), rep(".", 5), rep("#", 2), rep(".", 4), "#");
  const R9 = fila("#", ".", rep("#", 2), rep(".", 3), rep("#", 2), " ", rep("#", 2), rep(".", 3), rep("#", 2), ".", "#");
  const R10 = fila("#", rep(".", 6), "#", rep(" ", 3), "#", rep(".", 6), "#");
  const R11 = fila("#", rep(".", 3), rep("#", 2), ".", rep("#", 5), ".", rep("#", 2), rep(".", 3), "#");

  const MAZE = [
    R_BORDE, R1, R2, R2, R4, R5, R5, R4, R8, R9, R10, R11, R8, R4, R5, R5, R4, R2, R2, R1, R_BORDE,
  ];

  const HOME_TILE = { row: 10, col: 9 };
  const PACMAN_SPAWN = { row: 16, col: 9 };
  const HIGHSCORE_KEY = "piezasPlanas_pacman_highscore";

  const DURACION_SCATTER = 6;
  const DURACION_CHASE = 18;
  const DURACION_FRIGHTENED = 7;
  const TIEMPO_LISTO = 1.6;
  const VIDAS_INICIALES = 3;
  const PACMAN_SPEED = 150;
  const GHOST_SPEED_NORMAL = 128;
  const GHOST_SPEED_FRIGHTENED = 88;
  const GHOST_SPEED_EATEN = 260;

  let canvas, ctx, hudScore, hudVidas, hudHighscore;
  let rafId = null, onKeyDown = null;
  let lastTime = 0, tiempoTotal = 0;

  let pelletsGrid, pelletsRestantes, totalPelletsInicial;
  let score = 0, vidas = VIDAS_INICIALES, highScore = 0, chainCount = 0;
  let frightenedTimer = 0, freezeTimer = 0, motivoFreeze = null;
  let modoGlobal = "scatter", modoTimer = DURACION_SCATTER;
  let estadoJuego = "jugando"; // jugando | gameover | victoria
  let floatingTexts = [];

  const pacman = { row: 16, col: 9, x: 9 * CELL, y: 16 * CELL, dir: { dx: 0, dy: 0 }, facing: { dx: 1, dy: 0 }, procesado: false };
  let pacmanDesiredDir = { dx: 0, dy: 0 };

  const ghostsBase = [
    { name: "blinky", color: "#e74c3c", spawnRow: 9, spawnCol: 9, corner: { row: 1, col: 17 }, spawnState: "normal", spawnReleaseDelay: 0 },
    { name: "pinky", color: "#f5a9d0", spawnRow: 10, spawnCol: 9, corner: { row: 1, col: 1 }, spawnState: "housed", spawnReleaseDelay: 3 },
    { name: "inky", color: "#5dd7e0", spawnRow: 10, spawnCol: 8, corner: { row: 19, col: 17 }, spawnState: "housed", spawnReleaseDelay: 8 },
    { name: "clyde", color: "#f0a45a", spawnRow: 10, spawnCol: 10, corner: { row: 19, col: 1 }, spawnState: "housed", spawnReleaseDelay: 13 },
  ];
  const ghosts = ghostsBase.map((g) => Object.assign({}, g, {
    row: g.spawnRow, col: g.spawnCol, x: g.spawnCol * CELL, y: g.spawnRow * CELL,
    dir: { dx: 0, dy: 0 }, state: g.spawnState, releaseTimer: g.spawnReleaseDelay, procesado: false,
  }));

  // ── Utilidades de grilla ─────────────────────────────────────────────

  function isWalkable(tipo, row, col) {
    if (row < 0 || row >= ROWS || col < 0 || col >= COLS) return false;
    const ch = MAZE[row][col];
    if (ch === "#") return false;
    if (ch === " ") return tipo === "ghost";
    return true;
  }
  function snap(v) { return Math.round(v / CELL) * CELL; }
  function isAligned(e) {
    return Math.abs(e.x - snap(e.x)) < ALIGN_EPS && Math.abs(e.y - snap(e.y)) < ALIGN_EPS;
  }
  function tileDist2(r1, c1, r2, c2) { const dr = r1 - r2, dc = c1 - c2; return dr * dr + dc * dc; }

  function construirPelletsGrid() {
    return MAZE.map((row) => row.split("").map((ch) => (ch === "." ? 1 : ch === "o" ? 2 : 0)));
  }

  // ── IA de fantasmas ───────────────────────────────────────────────────

  function personalityTarget(g) {
    const pr = pacman.row, pc = pacman.col;
    const f = pacman.facing || { dx: 0, dy: 0 };
    if (g.name === "blinky") return { row: pr, col: pc };
    if (g.name === "pinky") return { row: pr + f.dy * 4, col: pc + f.dx * 4 };
    if (g.name === "inky") return { row: pr + f.dy * 2, col: pc + f.dx * 2 };
    // clyde: persigue si está lejos, si no se va a su esquina (tímido)
    const lejos = tileDist2(g.row, g.col, pr, pc) > 64;
    return lejos ? { row: pr, col: pc } : g.corner;
  }

  function mejorOpcion(g, opciones, objetivo) {
    let mejor = opciones[0], mejorD = Infinity;
    opciones.forEach((d) => {
      const dd = tileDist2(g.row + d.dy, g.col + d.dx, objetivo.row, objetivo.col);
      if (dd < mejorD) { mejorD = dd; mejor = d; }
    });
    return mejor;
  }

  function decideGhostDir(g) {
    const dirs = [{ dx: 0, dy: -1 }, { dx: 0, dy: 1 }, { dx: -1, dy: 0 }, { dx: 1, dy: 0 }];
    const reversa = { dx: -g.dir.dx, dy: -g.dir.dy };
    let opciones = dirs.filter((d) => isWalkable("ghost", g.row + d.dy, g.col + d.dx));
    if (opciones.length > 1) {
      opciones = opciones.filter((d) => !(d.dx === reversa.dx && d.dy === reversa.dy));
    }
    if (!opciones.length) opciones = [reversa];

    if (g.state === "eaten") return mejorOpcion(g, opciones, HOME_TILE);

    if (g.state === "frightened") {
      if (Math.random() < 0.6) return opciones[Math.floor(Math.random() * opciones.length)];
      const objetivo = { row: g.row + (g.row - pacman.row), col: g.col + (g.col - pacman.col) };
      return mejorOpcion(g, opciones, objetivo);
    }

    const objetivo = modoGlobal === "scatter" ? g.corner : personalityTarget(g);
    if (Math.random() < 0.15) return opciones[Math.floor(Math.random() * opciones.length)];
    return mejorOpcion(g, opciones, objetivo);
  }

  // ── Actualización de entidades ────────────────────────────────────────

  function comerPelletsEn(row, col) {
    const v = pelletsGrid[row][col];
    if (!v) return;
    pelletsGrid[row][col] = 0;
    pelletsRestantes--;
    if (v === 1) {
      score += 10;
    } else {
      score += 50;
      activarFrightened();
    }
    actualizarScoreUI();
  }

  function activarFrightened() {
    frightenedTimer = DURACION_FRIGHTENED;
    chainCount = 0;
    ghosts.forEach((g) => {
      if (g.state === "normal" || g.state === "leaving") {
        g.state = "frightened";
        g.dir = { dx: -g.dir.dx, dy: -g.dir.dy };
      }
    });
  }

  function updatePacman(dt) {
    if (isAligned(pacman)) {
      // Snap + comer pellet: SOLO una vez por casilla (si no, con velocidades
      // bajas quedaba atrapado — cada frame se detectaba "recién llegó" y lo
      // regresaba a la misma casilla antes de que alcanzara a salir de ella).
      if (!pacman.procesado) {
        pacman.procesado = true;
        pacman.x = snap(pacman.x); pacman.y = snap(pacman.y);
        pacman.row = pacman.y / CELL; pacman.col = pacman.x / CELL;
        comerPelletsEn(pacman.row, pacman.col);
      }

      // La dirección SÍ se reevalúa todos los frames mientras está alineado
      // (incluso si ya se "procesó" esta casilla) — así una tecla nueva se
      // toma en cuenta de inmediato, incluso si Pac-Man está detenido.
      let dir;
      if (isWalkable("pacman", pacman.row + pacmanDesiredDir.dy, pacman.col + pacmanDesiredDir.dx)) {
        dir = pacmanDesiredDir;
      } else if (isWalkable("pacman", pacman.row + pacman.dir.dy, pacman.col + pacman.dir.dx)) {
        dir = pacman.dir;
      } else {
        dir = { dx: 0, dy: 0 };
      }
      if (dir.dx !== 0 || dir.dy !== 0) pacman.facing = dir;
      pacman.dir = dir;
    } else {
      pacman.procesado = false;
    }
    pacman.x += pacman.dir.dx * PACMAN_SPEED * dt;
    pacman.y += pacman.dir.dy * PACMAN_SPEED * dt;
  }

  function updateGhost(g, dt) {
    if (g.state === "housed") {
      g.releaseTimer -= dt;
      if (g.releaseTimer <= 0) g.state = "leaving";
      return;
    }
    if (isAligned(g)) {
      if (!g.procesado) {
        g.procesado = true;
        g.x = snap(g.x); g.y = snap(g.y);
        g.row = g.y / CELL; g.col = g.x / CELL;

        if (g.state === "leaving") {
          if (g.col !== 9) {
            g.dir = { dx: g.col < 9 ? 1 : -1, dy: 0 };
          } else if (g.row > 9) {
            g.dir = { dx: 0, dy: -1 };
          } else {
            g.state = frightenedTimer > 0 ? "frightened" : "normal";
            g.dir = decideGhostDir(g);
          }
        } else if (g.state === "eaten") {
          if (g.row === HOME_TILE.row && g.col === HOME_TILE.col) {
            g.state = "housed";
            g.releaseTimer = 2;
            g.dir = { dx: 0, dy: 0 };
          } else {
            g.dir = decideGhostDir(g);
          }
        } else {
          g.dir = decideGhostDir(g);
        }
      }
    } else {
      g.procesado = false;
    }
    const speed = g.state === "frightened" ? GHOST_SPEED_FRIGHTENED
      : g.state === "eaten" ? GHOST_SPEED_EATEN
      : GHOST_SPEED_NORMAL;
    g.x += g.dir.dx * speed * dt;
    g.y += g.dir.dy * speed * dt;
  }

  function comerFantasma(g) {
    const puntos = 200 * Math.pow(2, chainCount);
    chainCount++;
    score += puntos;
    actualizarScoreUI();
    agregarFloatingText(g.x, g.y, "+" + puntos);
    g.state = "eaten";
  }

  function perderVida() {
    vidas--;
    actualizarVidasUI();
    if (vidas <= 0) {
      estadoJuego = "gameover";
      guardarHighScoreSiAplica();
    } else {
      resetPacman();
      ghosts.forEach(resetGhost);
      freezeTimer = 1.2;
      motivoFreeze = "vida";
    }
  }

  function checkColisiones() {
    ghosts.forEach((g) => {
      if (g.state === "housed") return;
      const dx = g.x - pacman.x, dy = g.y - pacman.y;
      const umbral = CELL * 0.6;
      if (dx * dx + dy * dy < umbral * umbral) {
        if (g.state === "frightened") comerFantasma(g);
        else if (g.state === "normal" || g.state === "leaving") perderVida();
      }
    });
  }

  function agregarFloatingText(x, y, texto) {
    floatingTexts.push({ x: x + CELL / 2, y: y + CELL / 2, texto, vida: 0.8, vidaTotal: 0.8 });
  }
  function actualizarFloatingTexts(dt) {
    floatingTexts.forEach((t) => (t.vida -= dt));
    floatingTexts = floatingTexts.filter((t) => t.vida > 0);
  }

  function actualizar(dt) {
    if (frightenedTimer > 0) {
      frightenedTimer -= dt;
      if (frightenedTimer <= 0) {
        ghosts.forEach((g) => { if (g.state === "frightened") g.state = "normal"; });
      }
    } else {
      modoTimer -= dt;
      if (modoTimer <= 0) {
        modoGlobal = modoGlobal === "scatter" ? "chase" : "scatter";
        modoTimer = modoGlobal === "scatter" ? DURACION_SCATTER : DURACION_CHASE;
      }
    }

    updatePacman(dt);
    ghosts.forEach((g) => updateGhost(g, dt));
    checkColisiones();
       actualizarFloatingTexts(dt);

    if (pelletsRestantes <= 0) {
      estadoJuego = "victoria";
      guardarHighScoreSiAplica();
    }
  }

  // ── Dibujo ────────────────────────────────────────────────────────────

  function dibujarMuros() {
    ctx.fillStyle = "#1b5e85";
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        if (MAZE[r][c] === "#") ctx.fillRect(c * CELL + 1, r * CELL + 1, CELL - 2, CELL - 2);
      }
    }
  }

  function dibujarPellets() {
    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const v = pelletsGrid[r][c];
        if (!v) continue;
        const cx = c * CELL + CELL / 2, cy = r * CELL + CELL / 2;
        if (v === 1) {
          ctx.fillStyle = "#f4f7fa";
          ctx.beginPath(); ctx.arc(cx, cy, 2.6, 0, Math.PI * 2); ctx.fill();
        } else {
          const pulso = 5.5 + Math.sin(tiempoTotal * 6) * 1.5;
          ctx.fillStyle = "#f4d03f";
          ctx.shadowColor = "#f4d03f"; ctx.shadowBlur = 8;
          ctx.beginPath(); ctx.arc(cx, cy, pulso, 0, Math.PI * 2); ctx.fill();
          ctx.shadowBlur = 0;
        }
      }
    }
  }

  function dibujarPacman() {
    const cx = pacman.x + CELL / 2, cy = pacman.y + CELL / 2;
    const radio = CELL / 2 - 2;
    let angulo = 0;
    if (pacman.facing.dx === 1) angulo = 0;
    else if (pacman.facing.dx === -1) angulo = Math.PI;
    else if (pacman.facing.dy === -1) angulo = -Math.PI / 2;
    else if (pacman.facing.dy === 1) angulo = Math.PI / 2;

    const abertura = (Math.abs(Math.sin(tiempoTotal * 9)) * 0.28 + 0.04) * Math.PI;

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angulo);
    ctx.fillStyle = "#f4d03f";
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, radio, abertura, Math.PI * 2 - abertura);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function dibujarFantasmaCuerpo(g, soloOjos) {
    const cx = g.x + CELL / 2, cy = g.y + CELL / 2;
    const r = CELL / 2 - 2;
    if (!soloOjos) {
      let color = g.color;
      if (g.state === "frightened") {
        const parpadeo = frightenedTimer < 2 && Math.floor(tiempoTotal * 8) % 2 === 0;
        color = parpadeo ? "#f4f7fa" : "#2455c9";
      }
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(cx, cy - 1, r, Math.PI, Math.PI * 2, false);
      ctx.lineTo(cx + r, cy + r - 2);
      ctx.lineTo(cx - r, cy + r - 2);
      ctx.closePath();
      ctx.fill();
    }
    const dir = g.dir;
    [-1, 1].forEach((s) => {
      const sx = cx + s * 5;
      ctx.fillStyle = "#f4f7fa";
      ctx.beginPath(); ctx.arc(sx, cy - 3, 4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#1f2937";
      ctx.beginPath(); ctx.arc(sx + dir.dx * 2, cy - 3 + dir.dy * 2, 2, 0, Math.PI * 2); ctx.fill();
    });
  }

  function dibujarFantasmas() {
    ghosts.forEach((g) => dibujarFantasmaCuerpo(g, g.state === "eaten"));
  }

  function dibujarFloatingTexts() {
    ctx.textAlign = "center";
    ctx.font = "bold 13px 'Segoe UI', sans-serif";
    floatingTexts.forEach((t) => {
      ctx.globalAlpha = Math.max(0, t.vida / t.vidaTotal);
      ctx.fillStyle = "#f4d03f";
      ctx.fillText(t.texto, t.x, t.y - (1 - t.vida / t.vidaTotal) * 20);
      ctx.globalAlpha = 1;
    });
  }

  function dibujarMensaje(texto, color) {
    ctx.fillStyle = "rgba(4,7,13,0.55)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.font = "bold 26px 'Segoe UI', sans-serif";
    ctx.fillText(texto, canvas.width / 2, canvas.height / 2);
  }

  function dibujarMensajeFinal(titulo, sub, color) {
    ctx.fillStyle = "rgba(4,7,13,0.75)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.font = "bold 26px 'Segoe UI', sans-serif";
    ctx.fillText(titulo, canvas.width / 2, canvas.height / 2 - 14);
    ctx.fillStyle = "#f4f7fa";
    ctx.font = "13px 'Segoe UI', sans-serif";
    ctx.fillText(sub, canvas.width / 2, canvas.height / 2 + 14);
    ctx.font = "12px 'Segoe UI', sans-serif";
    ctx.fillText(`Puntaje: ${score}  ·  Mejor: ${highScore}`, canvas.width / 2, canvas.height / 2 + 38);
  }

  function dibujar() {
    ctx.fillStyle = "#04070d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    dibujarMuros();
    dibujarPellets();
    dibujarFantasmas();
    dibujarPacman();
    dibujarFloatingTexts();

    if (freezeTimer > 0 && motivoFreeze === "listo") {
      dibujarMensaje("¡LISTO!", "#f4d03f");
    } else if (estadoJuego === "gameover") {
      dibujarMensajeFinal("GAME OVER", "Presiona espacio para reintentar", "#e74c3c");
    } else if (estadoJuego === "victoria") {
      dibujarMensajeFinal("¡GANASTE!", "Presiona espacio para jugar de nuevo", "#2ecc71");
    }
  }

  // ── Ciclo de vida del juego ───────────────────────────────────────────

  function resetPacman() {
    pacman.row = PACMAN_SPAWN.row; pacman.col = PACMAN_SPAWN.col;
    pacman.x = pacman.col * CELL; pacman.y = pacman.row * CELL;
    pacman.dir = { dx: 0, dy: 0 };
    pacman.facing = { dx: 1, dy: 0 };
    pacman.procesado = false;
    pacmanDesiredDir = { dx: 0, dy: 0 };
  }
  function resetGhost(g) {
    g.row = g.spawnRow; g.col = g.spawnCol;
    g.x = g.spawnCol * CELL; g.y = g.spawnRow * CELL;
    g.dir = { dx: 0, dy: 0 };
    g.state = g.spawnState;
    g.releaseTimer = g.spawnReleaseDelay;
    g.procesado = false;
  }

  function actualizarScoreUI() {
    if (hudScore) hudScore.textContent = String(score);
    guardarHighScoreSiAplica();
  }
  function actualizarVidasUI() {
    if (hudVidas) hudVidas.textContent = String(Math.max(0, vidas));
  }
  function actualizarHighScoreUI() {
    if (hudHighscore) hudHighscore.textContent = String(highScore);
  }
  function guardarHighScoreSiAplica() {
    if (score > highScore) {
      highScore = score;
      actualizarHighScoreUI();
      try { localStorage.setItem(HIGHSCORE_KEY, String(highScore)); } catch (e) { /* localStorage bloqueado, no pasa nada */ }
    }
  }

  function reiniciarJuego() {
    pelletsGrid = construirPelletsGrid();
    pelletsRestantes = totalPelletsInicial;
    score = 0;
    vidas = VIDAS_INICIALES;
    chainCount = 0;
    frightenedTimer = 0;
    modoGlobal = "scatter";
    modoTimer = DURACION_SCATTER;
    estadoJuego = "jugando";
    freezeTimer = TIEMPO_LISTO;
    motivoFreeze = "listo";
    floatingTexts = [];
    resetPacman();
    ghosts.forEach(resetGhost);
    actualizarScoreUI();
    actualizarVidasUI();
    actualizarHighScoreUI();
  }

  function loop(now) {
    const dt = Math.min(DT_MAX, (now - lastTime) / 1000);
    lastTime = now;
    tiempoTotal += dt;

    if (freezeTimer > 0) {
      freezeTimer -= dt;
      if (freezeTimer <= 0) motivoFreeze = null;
    } else if (estadoJuego === "jugando") {
      actualizar(dt);
    }
    dibujar();
    rafId = requestAnimationFrame(loop);
  }

  function instalarControles() {
    const teclas = {
      ArrowUp: { dx: 0, dy: -1 }, w: { dx: 0, dy: -1 }, W: { dx: 0, dy: -1 },
      ArrowDown: { dx: 0, dy: 1 }, s: { dx: 0, dy: 1 }, S: { dx: 0, dy: 1 },
      ArrowLeft: { dx: -1, dy: 0 }, a: { dx: -1, dy: 0 }, A: { dx: -1, dy: 0 },
      ArrowRight: { dx: 1, dy: 0 }, d: { dx: 1, dy: 0 }, D: { dx: 1, dy: 0 },
    };
    onKeyDown = (ev) => {
      if (teclas[ev.key]) {
        ev.preventDefault();
        pacmanDesiredDir = teclas[ev.key];
        return;
      }
      if (ev.key === " ") {
        ev.preventDefault();
        if (estadoJuego === "gameover" || estadoJuego === "victoria") reiniciarJuego();
      }
    };
    document.addEventListener("keydown", onKeyDown);
  }

  function iniciar(canvasEl, scoreEl, vidasEl, highscoreEl) {
    detener(); // limpieza defensiva por si quedó algo corriendo de una apertura anterior

    canvas = canvasEl;
    hudScore = scoreEl; hudVidas = vidasEl; hudHighscore = highscoreEl;
    canvas.width = COLS * CELL;
    canvas.height = ROWS * CELL;
    ctx = canvas.getContext("2d");

    try { highScore = parseInt(localStorage.getItem(HIGHSCORE_KEY), 10) || 0; } catch (e) { highScore = 0; }

    totalPelletsInicial = 0;
    MAZE.forEach((row) => {
      for (const ch of row) if (ch === "." || ch === "o") totalPelletsInicial++;
    });

    reiniciarJuego();
    instalarControles();
    lastTime = performance.now();
    tiempoTotal = 0;
    rafId = requestAnimationFrame(loop);
  }

  function detener() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    if (onKeyDown) document.removeEventListener("keydown", onKeyDown);
    onKeyDown = null;
  }

  return { iniciar, detener };
})();
