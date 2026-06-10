# SPEC — Analizador de Inversiones ("Analista Incansable")

> **Documento de especificación para implementación con Claude Code.**
> Propietario: Joaquín. Infraestructura: Mini PC (Ubuntu Server 26.04).
> Filosofía: esta herramienta **analiza y vigila, NO predice**. Automatiza el checklist
> fundamental (Paso 2), vigila zonas de precio y sintetiza documentos. Nunca genera
> señales automáticas de compra/venta. La decisión es siempre del usuario.

---

## 0. Contexto de infraestructura (estado actual)

### Mini PC (servidor donde vive TODO el proyecto)
| Item | Valor |
|---|---|
| Hardware | AMD Ryzen 9 4900H, 32 GB RAM |
| SO | Ubuntu Server 26.04 LTS |
| Acceso SSH | `ssh <usuario>@<servidor>` (o IP Tailscale `<ip-privada-del-servidor>`) |
| Tailscale | ✅ Instalado y operativo |
| Ollama | ✅ Instalado, modelo Llama 3.1 8B disponible |
| Open WebUI | ✅ Puerto 3000 |
| Jupyter Lab | ✅ Puerto 8888 (servicio systemd) |
| Python | ✅ (verificar versión: `python3 --version`, se asume 3.12+) |
| Qdrant | ❌ NO instalado (se instala en Fase 4) |
| n8n | ❌ NO instalado (se instala en Fase 3) |
| Docker | ⚠️ VERIFICAR (`docker --version`). Necesario para n8n y Qdrant. Si no está, instalarlo en Fase 3 |

### Portátil (cliente de desarrollo)
| Item | Valor |
|---|---|
| Equipo | Portátil con GPU |
| Tailscale | `<ip-privada-del-portatil>` |
| Rol | Desarrollo remoto (VS Code Remote-SSH o terminal SSH) + uso diario |

### Puertos asignados (evitar conflictos)
| Servicio | Puerto | Estado |
|---|---|---|
| Open WebUI | 3000 | En uso |
| Jupyter Lab | 8888 | En uso |
| n8n | 5678 | Reservado (Fase 3) |
| Qdrant | 6333/6334 | Reservado (Fase 4) |

### Dónde se trabaja cada cosa
- **Todo el código y los servicios se ejecutan en el Mini PC.**
- **Desarrollo:** desde el portátil con VS Code + extensión Remote-SSH conectado a
  `<usuario>@<servidor>`, o con Claude Code lanzado en una sesión SSH dentro del Mini PC.
- **Recomendado:** lanzar Claude Code DENTRO del Mini PC (vía SSH) para que cree, ejecute
  y pruebe el código directamente donde va a vivir.
- **Exploración de datos puntual:** Jupyter Lab ya existente (puerto 8888).

---

## 1. Objetivo del sistema

Construir una herramienta personal que:
1. **Vigile la watchlist** — precios diarios, distancia a zonas de entrada definidas, alertas.
2. **Automatice el checklist fundamental** — score por empresa con los criterios del método
   personal de análisis (ver §5).
3. **Detecte banderas rojas** — dilución, deterioro de márgenes, FCF negativo.
4. **Contextualice las alertas** — al entrar en zona, adjuntar titulares recientes
   (responder a "¿POR QUÉ ha caído?", regla anti-trampa de valor).
5. **(Fase avanzada) Sintetice documentos** — RAG sobre 10-K/10-Q para preguntar por
   riesgos, guidance y cambios de tesis.

### Lo que el sistema NO hace (por diseño)
- ❌ NO predice precios ni genera señales de compra/venta automáticas.
- ❌ NO opera contra ningún broker (sin integración con Trade Republic).
- ❌ NO sustituye el análisis humano: produce datos y síntesis, no decisiones.

---

## 2. Arquitectura general

```
┌─────────────────────────── MINI PC ───────────────────────────┐
│                                                                │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────┐  │
│  │ M1: INGESTA  │──▶│ M2: ANÁLISIS │──▶│ M3: ALERTAS (n8n) │──┼─▶ Telegram
│  │ yfinance     │   │ score+zonas  │   │ cron + telegram   │  │
│  │ cron diario  │   │              │   └───────────────────┘  │
│  └──────┬───────┘   └──────┬───────┘                          │
│         ▼                  ▼                                  │
│  ┌─────────────────────────────────┐   ┌───────────────────┐  │
│  │        SQLite (datos.db)        │   │ M4: RAG (Fase 4)  │  │
│  └─────────────────────────────────┘   │ Qdrant + Ollama   │  │
│                                        │ SEC EDGAR (10-K)  │  │
│                                        └───────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### Stack y decisiones técnicas
| Decisión | Elección | Por qué |
|---|---|---|
| Lenguaje | Python 3.12+ | Ecosistema financiero, ya en el Mini PC |
| Datos de mercado | `yfinance` | Gratis, sin API key. Limitación aceptada: datos con retardo y a veces inconsistentes — suficiente para position trading (horizonte 3-12 meses, no intradía) |
| Base de datos | SQLite | Cero administración, un solo usuario, archivo único fácil de respaldar |
| Entorno | `venv` dedicado en `~/inversiones/.venv` | Aislar dependencias del sistema |
| Automatización | cron (Fases 1-2) → n8n (Fase 3) | Empezar simple; n8n añade flujos visuales y Telegram |
| Vector DB | Qdrant (Docker) | Ya previsto en el roadmap del lab de IA |
| LLM local | Ollama + Llama 3.1 8B | Ya instalado |
| Filings SEC | API EDGAR (gratuita, sin key; requiere User-Agent identificativo) | Fuente primaria oficial |
| Config | `config.yaml` + `.env` (token Telegram) | Separar datos de código; `.env` NUNCA se sube a git |

---

## 3. Estructura del proyecto

```
~/inversiones/
├── SPEC_analizador_inversiones.md   # este documento
├── README.md                        # quick start (lo genera Claude Code)
├── config.yaml                      # watchlist, zonas, umbrales del score
├── .env                             # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (git-ignored)
├── .gitignore                       # .env, .venv, *.db, __pycache__
├── requirements.txt
├── datos.db                         # SQLite (git-ignored)
├── src/
│   ├── __init__.py
│   ├── ingesta.py        # M1: descarga precios + fundamentales → SQLite
│   ├── analisis.py       # M2: score fundamental + análisis técnico de zonas
│   ├── alertas.py        # M3: lógica de alertas (la llama n8n o cron)
│   ├── titulares.py      # M3b: noticias recientes por ticker (yfinance news)
│   ├── informe.py        # genera informe diario en texto/markdown
│   └── db.py             # esquema y helpers de SQLite
├── rag/                  # Fase 4
│   ├── descarga_edgar.py # baja 10-K/10-Q de SEC EDGAR
│   ├── indexa.py         # trocea e indexa en Qdrant
│   └── consulta.py       # CLI de preguntas (Ollama + Qdrant)
├── backtest/             # Fase 5 (opcional)
│   └── reglas.py
└── tests/
    └── test_analisis.py  # tests del score con datos sintéticos
```

---

## 4. Esquema de base de datos (SQLite)

```sql
-- Precios diarios (OHLCV)
CREATE TABLE precios (
    ticker TEXT NOT NULL,
    fecha DATE NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volumen INTEGER,
    PRIMARY KEY (ticker, fecha)
);

-- Fundamentales (snapshot por fecha de descarga; histórico de snapshots)
CREATE TABLE fundamentales (
    ticker TEXT NOT NULL,
    fecha_snapshot DATE NOT NULL,
    ingresos_ttm REAL,            -- USD
    crecimiento_ingresos_yoy REAL,-- % (TTM vs TTM-1y)
    margen_bruto REAL,            -- %
    margen_operativo REAL,        -- %
    margen_neto REAL,             -- %
    fcf_ttm REAL,                 -- USD
    margen_fcf REAL,              -- %
    deuda_total REAL,
    caja REAL,
    deuda_neta_ebitda REAL,       -- x (NULL si EBITDA <= 0)
    roe REAL,                     -- %
    acciones_circulacion REAL,
    dilucion_yoy REAL,            -- % crecimiento de acciones
    per_ttm REAL,                 -- NULL si pérdidas
    per_forward REAL,
    ev_ventas REAL,
    PRIMARY KEY (ticker, fecha_snapshot)
);

-- Resultado del score (histórico para ver evolución)
CREATE TABLE scores (
    ticker TEXT NOT NULL,
    fecha DATE NOT NULL,
    score_total REAL,             -- 0-100
    detalle_json TEXT,            -- desglose por criterio + banderas rojas
    PRIMARY KEY (ticker, fecha)
);

-- Alertas enviadas (anti-spam: no repetir la misma alerta cada día)
CREATE TABLE alertas_enviadas (
    ticker TEXT NOT NULL,
    tipo TEXT NOT NULL,           -- 'entrada_zona' | 'bandera_roja' | 'cruce_media'
    fecha DATE NOT NULL,
    payload TEXT,
    PRIMARY KEY (ticker, tipo, fecha)
);
```

---

## 5. Motor de score fundamental (checklist Paso 2 codificado)

Score 0-100. Pesos y umbrales en `config.yaml` (modificables sin tocar código).

| # | Criterio | Métrica | Umbral verde (puntos) | Umbral amarillo (½ puntos) | Peso |
|---|---|---|---|---|---|
| 1 | Crecimiento | Ingresos YoY (TTM) | > 20% | 10-20% | 20 |
| 2 | Calidad de margen | Margen bruto | > 50% | 35-50% | 10 |
| 3 | Rentabilidad real | FCF TTM | > 0 y creciente | > 0 estable | 20 |
| 4 | Conversión | Margen FCF | > 10% | 5-10% | 10 |
| 5 | Balance | Deuda neta/EBITDA | < 1x (o caja neta) | 1-3x | 10 |
| 6 | Retorno | ROE | > 15% | 8-15% | 10 |
| 7 | Dilución | Crec. acciones YoY | < 2% | 2-5% | 10 |
| 8 | Beneficio acompaña | Crec. beneficio ≥ crec. ingresos | Sí | Beneficio > 0 pero crece menos | 10 |

**Banderas rojas (se listan SIEMPRE junto al score, no se promedian):**
- 🚩 Dilución > 5% anual
- 🚩 FCF negativo
- 🚩 Margen bruto en caída > 3 puntos porcentuales YoY
- 🚩 Deuda neta/EBITDA > 3x
- 🚩 Crecimiento de ingresos decelerando > 10 p.p. vs año anterior
- 🚩 Manual (campo en config): litigios, riesgo de crédito, dependencia de un cliente
  — ej.: ZETA litigio de valores; PGY exposición a ciclo de crédito

**Regla de presentación:** el informe muestra score + desglose + banderas. Nunca un
"comprar/vender". El campo `nota_manual` de cada ticker en config se imprime SIEMPRE
junto al score (p. ej. "ZETA: tamaño pequeño por litigio").

---

## 6. Datos semilla (config.yaml inicial)

```yaml
# ⚠️ Zonas definidas el 09-06-2026. REVISAR tras cada earnings o noticia relevante.
# No son recomendaciones: son niveles de referencia propios para vigilancia.
watchlist:
  ZETA:
    zona_entrada: [18.5, 19.5]
    soporte_profundo: [17.8, 18.6]
    resistencia_clave: 24.90
    nota_manual: "LITIGIO de valores vivo (Davoodi, SDNY). Cola binaria. TAMAÑO PEQUEÑO."
    earnings_proximos: "2026-08 (aprox)"
  MGNI:
    zona_entrada: [12.5, 13.5]
    resistencia_clave: 15.50
    nota_manual: "Entrada alternativa: ruptura confirmada >15.50-16. Legacy en declive vs CTV."
  AXON:
    zona_entrada: [400, 420]
    soporte_profundo: 380
    nota_manual: "Compounder de calidad: entrada ESCALONADA, no de golpe. Earnings ~11-ago."
  PGY:
    zona_entrada: [11.0, 12.5]
    nota_manual: "Beta 3.5 + riesgo ciclo de crédito. TAMAÑO MÍNIMO aunque toque zona."
secundarios:
  HAE: { nota_manual: "Defensiva, crecimiento bajo. Sin zona definida aún." }
  CPNG: { nota_manual: "Turnaround sin confirmar. Solo vigilar fundamentales." }

umbrales_score:  # ver §5; editable
  crecimiento_verde: 20
  margen_bruto_verde: 50
  dilucion_maxima: 5
  # ... resto según tabla §5

alertas:
  hora_cron: "07:30"          # hora local Madrid, tras cierre USA del día anterior
  proximidad_zona_pct: 3      # avisar también cuando esté a <3% de la zona
  antispam_dias: 5            # no repetir alerta idéntica en N días
```

---

## 7. FASES DE IMPLEMENTACIÓN

> Cada fase es usable por sí sola. NO empezar una fase hasta que la anterior pase su
> criterio de "hecho". A Claude Code se le pide UNA fase por sesión.

---

### FASE 0 — Preparación del entorno (30-45 min) · 📍 Mini PC vía SSH

**Desde dónde:** terminal del portátil → `ssh <usuario>@<servidor>`.

**Tareas:**
1. Verificar versiones: `python3 --version` (≥3.10), `git --version`, `docker --version`
   (si Docker falta, anotar: se instalará en Fase 3, no bloquea Fases 0-2).
2. Crear proyecto: `mkdir -p ~/inversiones && cd ~/inversiones && git init`.
3. Entorno virtual: `python3 -m venv .venv && source .venv/bin/activate`.
4. `pip install yfinance pandas pyyaml python-dotenv`.
5. Copiar este SPEC al directorio del proyecto.
6. Crear `.gitignore` (`.env`, `.venv/`, `*.db`, `__pycache__/`).
7. (Opcional pero recomendado) Instalar Claude Code en el Mini PC y lanzarlo desde
   `~/inversiones` — verificar instrucciones actuales en docs.claude.com.

**Hecho cuando:** `python -c "import yfinance; print(yfinance.download('ZETA', period='5d'))"`
devuelve datos dentro del venv.

---

### FASE 1 — Tracker de watchlist (1-2 tardes) · 📍 Mini PC

**Objetivo:** script que imprime una tabla diaria con la distancia de cada ticker a su zona.

**Tareas para Claude Code:**
1. `config.yaml` con los datos semilla de §6.
2. `src/db.py`: crear SQLite con el esquema de §4 (solo tabla `precios` por ahora).
3. `src/ingesta.py`: descargar OHLCV diario de la watchlist (yfinance, periodo 1y),
   upsert en `precios`. Manejo de errores: si un ticker falla, log y continuar.
4. `src/informe.py` (versión mínima): tabla en consola →
   `ticker | cierre | zona | distancia % | RSI(14) | vs SMA50 | vs SMA200 | nota_manual`.
   Calcular RSI y SMAs con pandas sobre los datos guardados (sin librerías extra).
5. Cron diario provisional: `crontab -e` →
   `30 7 * * 2-6 cd ~/inversiones && .venv/bin/python -m src.ingesta && .venv/bin/python -m src.informe >> informe_diario.log 2>&1`
   (martes-sábado a las 07:30: tras el cierre de USA del día anterior, hora Madrid).

**Hecho cuando:** ejecutar `python -m src.informe` muestra la tabla con los 4 tickers
y la distancia a zona coincide con un cálculo manual (verificar 1 ticker a mano).

---

### FASE 2 — Screener fundamental (1-2 semanas) · 📍 Mini PC

**Objetivo:** score 0-100 + banderas rojas por empresa, guardado con histórico.

**Tareas para Claude Code:**
1. Ampliar `src/db.py` con tablas `fundamentales` y `scores`.
2. `src/ingesta.py`: añadir descarga de fundamentales vía yfinance
   (`Ticker.info`, `Ticker.financials`, `Ticker.cashflow`, `Ticker.balance_sheet`).
   ⚠️ yfinance puede devolver campos vacíos o nombres cambiantes: cada métrica que
   falte se guarda como NULL y se muestra como "s/d" — NUNCA inventar ni interpolar.
3. `src/analisis.py`: implementar la tabla de §5 (umbrales desde config).
   Salida: score + desglose por criterio + lista de banderas + nota_manual.
4. `src/informe.py`: añadir sección fundamental al informe diario.
5. `tests/test_analisis.py`: 3 casos sintéticos —empresa "verde total" (≈100),
   "amarilla" (≈50), "roja" (<30 con banderas)— para validar la lógica sin red.
6. Probar también con 2-3 tickers fuera de la watchlist (p. ej. AAPL, KO) para
   verificar robustez con perfiles distintos.

**Hecho cuando:** los tests pasan y el score de ZETA refleja la realidad conocida:
crecimiento alto ✓, margen bruto ~60% ✓, FCF positivo ✓, bandera de dilución 🚩,
nota del litigio visible.

---

### FASE 3 — Alertas automáticas con n8n + Telegram (2-4 días) · 📍 Mini PC + móvil

**Objetivo:** dejar de mirar el mercado; que el sistema avise.

**Prerequisitos (instalar ahora):**
1. Docker si no está: seguir la guía oficial de Docker para Ubuntu (verificar
   instrucciones actuales; el método cambia entre versiones).
2. n8n en Docker:
   ```bash
   docker run -d --name n8n --restart unless-stopped \
     -p 5678:5678 -v ~/.n8n:/home/node/.n8n n8nio/n8n
   ```
   UI accesible vía Tailscale: `http://<ip-privada-del-servidor>:5678`.
3. Bot de Telegram: crear con @BotFather desde el móvil → token al `.env`.
   Obtener `chat_id` (mensaje al bot + endpoint getUpdates).

**Tareas para Claude Code:**
1. `src/titulares.py`: últimos 3-5 titulares por ticker (yfinance `Ticker.news`;
   si falla, devolver lista vacía sin romper).
2. `src/alertas.py`: evalúa condiciones y devuelve JSON de alertas pendientes:
   - `entrada_zona`: cierre dentro de zona_entrada
   - `proximidad`: a <3% de la zona (configurable)
   - `cruce_media`: cierre cruza SMA200 (ambas direcciones)
   - `bandera_roja_nueva`: aparece una bandera que ayer no estaba
   - Anti-spam vía tabla `alertas_enviadas`.
   - **Toda alerta de zona incluye los titulares** (regla "¿por qué ha caído?")
     y la `nota_manual` del ticker (p. ej. recordatorio de tamaño en ZETA/PGY).
3. Flujo n8n: Schedule (07:30 mar-sáb) → Execute Command
   (`~/inversiones/.venv/bin/python -m src.alertas --json`) → If hay alertas → Telegram.
4. Retirar el cron de la Fase 1 (n8n lo sustituye) y añadir al flujo el envío del
   informe diario completo una vez por semana (p. ej. sábado).

**Hecho cuando:** llega un Telegram de prueba forzando una zona ficticia (poner
temporalmente la zona de un ticker en su precio actual, ejecutar, verificar, revertir).

---

### FASE 4 — RAG de documentos SEC (2-3 semanas) · 📍 Mini PC

> Coincide con la Fase 3 del roadmap del lab de IA (Qdrant + RAG): mismo aprendizaje,
> caso de uso real.

**Prerequisitos:**
1. Qdrant en Docker:
   ```bash
   docker run -d --name qdrant --restart unless-stopped \
     -p 6333:6333 -p 6334:6334 -v ~/qdrant_storage:/qdrant/storage qdrant/qdrant
   ```
2. Modelo de embeddings en Ollama: `ollama pull nomic-embed-text` (ligero, corre bien
   en CPU del Ryzen 9).
3. `pip install qdrant-client requests beautifulsoup4`.

**Tareas para Claude Code:**
1. `rag/descarga_edgar.py`: bajar últimos 10-K y 10-Q de cada ticker desde la API de
   SEC EDGAR (`data.sec.gov`, gratuita; OBLIGATORIO User-Agent con nombre y email;
   respetar límite ~10 req/s). Guardar en `rag/docs/<ticker>/`.
2. `rag/indexa.py`: extraer texto, trocear (~1000 tokens, solapamiento 150),
   embeddings con nomic-embed-text → colección Qdrant por ticker, metadatos
   (ticker, tipo de filing, fecha, sección).
3. `rag/consulta.py`: CLI → pregunta → recuperar top-k de Qdrant → prompt a
   Llama 3.1 8B vía API de Ollama → respuesta CON citas de las secciones fuente.
   El prompt del sistema debe exigir: "responde SOLO con lo que aparezca en los
   fragmentos; si no está, di que no aparece" (anti-alucinación).
4. Preguntas de validación: "¿Qué riesgos legales menciona ZETA en su último 10-K?",
   "¿Qué dice AXON de su backlog?", "Compara el guidance de PGY con el trimestre anterior".

**Hecho cuando:** las 3 preguntas de validación devuelven respuestas con citas
correctas verificables contra el documento original.

**Nota de rendimiento:** Llama 3.1 8B en CPU (sin GPU en el Mini PC) responde lento
(decenas de segundos). Aceptable para consultas puntuales. Alternativa: exponer Ollama
del portátil (con GPU, Tailscale <ip-privada-del-portatil>) y apuntar `consulta.py` allí
cuando el portátil esté encendido — dejarlo como parámetro en config.

---

### FASE 5 — Backtesting de reglas (opcional) · 📍 Mini PC (Jupyter)

**Objetivo:** SOLO aprendizaje. Probar reglas mecánicas sobre histórico para entender
su comportamiento, no para "validar" estrategias.

**Tareas:** `backtest/reglas.py` con: descarga de 5-10 años de histórico, regla
parametrizable (ej. "compra si precio entra en banda X bajo SMA200 y RSI<30; vende a
+20% o -10%"), evaluación **walk-forward** (entrenar/definir en ventana A, probar en
ventana B posterior), métricas (CAGR, max drawdown, % aciertos) y comparación SIEMPRE
contra buy&hold del SPY.

**Advertencias obligatorias en el README de esta fase:**
- Backtest bonito ≠ futuro. El overfitting es la norma.
- Sesgo de supervivencia: la watchlist actual ya es una selección a posteriori.
- Si una regla parece increíble, lo más probable es que esté mal medida.

---

## 8. Cómo trabajar con Claude Code (guía de uso)

1. **Sesión:** SSH al Mini PC → `cd ~/inversiones` → lanzar Claude Code.
2. **Primer prompt de cada fase (plantilla):**
   > "Lee SPEC_analizador_inversiones.md. Implementa SOLO la Fase N siguiendo el spec
   > al pie de la letra. No avances a la fase siguiente. Al terminar, dime cómo probar
   > el criterio de 'hecho' de la fase."
3. **Una fase por sesión.** Probar el criterio de "hecho" personalmente antes de seguir.
4. **Commit por fase:** `git add -A && git commit -m "Fase N completa"`.
5. Si Claude Code propone desviarse del spec, pedirle que lo justifique primero y
   actualizar este documento si la mejora convence — el spec es la fuente de verdad.
6. Mantener §0 (estado de instalaciones) actualizado al completar cada fase.

---

## 9. Mantenimiento y límites conocidos

- **Zonas de precio:** caducan. Revisar tras cada earnings (AXON ~11-ago, PGY ~6-ago,
  ZETA/MGNI agosto aprox.) y ante cualquier noticia del litigio de ZETA.
- **yfinance:** no es API oficial; puede romperse con cambios de Yahoo. Si falla,
  `pip install -U yfinance` suele resolverlo. Plan B futuro: Financial Modeling Prep
  (free tier con API key) — dejar la capa de ingesta desacoplada para poder cambiar.
- **SEC EDGAR:** solo empresas cotizadas en USA. Cubre toda la watchlist actual.
- **Backups:** `datos.db` y `config.yaml` → copia semanal (basta `scp` al portátil o
  un cron de `cp` a otra carpeta versionada).
- **Seguridad:** todo queda dentro de Tailscale; NO exponer n8n/Qdrant a internet
  (no usar el túnel de Cloudflare para estos servicios).
- **Disclaimer permanente:** herramienta de análisis personal. No genera consejos de
  inversión. Las decisiones de compra/venta, el dimensionamiento (fórmula del Paso 1)
  y la gestión del riesgo son siempre del usuario.
