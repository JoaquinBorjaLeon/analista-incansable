# ANEXO 2 al SPEC — Fase 7: Screener de descubrimiento

> Amplía `SPEC_analizador_inversiones.md` y `SPEC_anexo_fases_2_5_y_6.md`.
> Mismas reglas: una fase por sesión, criterio de "hecho", la herramienta analiza y NO decide.
> Prerequisito: Fases 1 y 2 completas (reutiliza el motor de score de `src/analisis.py`).
> Orden global recomendado: 3 → 2.5 → 4 → 6 → 7 → (5 opcional).

---

## FASE 7 — Screener de descubrimiento semanal (1 semana) · 📍 Mini PC

**Objetivo:** descubrir candidatas FUERA de la watchlist aplicando los criterios
automatizables del score a un universo amplio, una vez por semana. El resultado es una
lista de estudio — materia prima para el análisis manual del usuario — NUNCA una lista
de compra. Una empresa solo entra en la watchlist cuando el usuario le ha construido
tesis y zona (Fase 2.5).

### Principio de diseño (el embudo)

```
Universo (~900)  →  Screener semanal  →  Top 10-15  →  Análisis MANUAL del usuario
                                                        └─ si convence → watchlist
                                                           (con tesis + zona propias)
```

El screener NO añade nada a la watchlist automáticamente. La promoción es siempre
manual, editando config.yaml.

### 1. Universo de tickers — `src/universo.py`

- Obtener los constituyentes de **S&P 500 + S&P MidCap 400** (~900 tickers).
  Fuente: tablas públicas de Wikipedia (parseo con pandas.read_html) — documentar la
  URL exacta usada y manejar el fallo de parseo con gracia (si Wikipedia cambia el
  formato, log de error claro y usar el último universo cacheado).
- Cachear en SQLite (tabla `universo`: ticker, nombre, sector, indice, fecha_actualizacion).
- Refrescar el universo una vez al MES (los índices cambian poco); el screener semanal
  usa la caché.
- Excluir SIEMPRE: tickers ya en watchlist o secundarios, y tickers en la lista
  `descartados` de config (ver §4).

### 2. Screener — `src/descubrimiento.py`

- Frecuencia: **semanal** (domingo por la tarde, mercado cerrado, datos de la semana
  completos), vía cron o flujo n8n si la Fase 3 ya está hecha.
- **Rate-limiting obligatorio** (yfinance no es API oficial):
  - Procesar en tandas de ~50 tickers con pausa de 30-60 s entre tandas.
  - Pausa aleatoria de 0.5-1.5 s entre tickers dentro de la tanda.
  - Si yfinance devuelve errores en cadena (>10 seguidos), abortar la pasada, registrar
    el punto donde se quedó y reanudar desde ahí en la siguiente ejecución (campo de
    progreso en SQLite). NUNCA martillear la fuente.
  - Duración esperada de la pasada completa: 1-2 horas. Es aceptable: corre sola en domingo.
- Para cada ticker: descargar fundamentales (reutilizar `descargar_fundamentales()` de
  la Fase 2) y calcular el score con el MISMO motor de `src/analisis.py` (cero lógica
  duplicada — si los umbrales cambian en config, cambian para todo).
- Guardar resultados en tabla `descubrimiento` (ticker, fecha_pasada, score,
  detalle_json, banderas).

### 3. Informe de descubrimiento

- Al terminar la pasada, generar `descubrimiento_YYYY-MM-DD.md` en el proyecto:
  - **Top 15 por score** (excluyendo watchlist/descartados), con: ticker, nombre,
    sector, score, desglose breve (los 2 mejores y 2 peores criterios), banderas.
  - Aviso fijo en cabecera: "Lista de ESTUDIO generada por criterios cuantitativos.
    Sin tesis, sin zona y sin análisis cualitativo. NO es una lista de compra. El
    score no ve: fosos, litigios, ciclos de crédito, calidad del management, ni
    ningún riesgo fuera de los estados financieros."
  - Sección "novedades vs semana anterior": entradas y salidas del top 15 (la
    persistencia en el top es señal más interesante que una aparición puntual).
- Si la Fase 3 está hecha: enviar por Telegram un resumen (top 5 + enlace mental al
  informe completo); si no, el .md queda en el proyecto.

### 4. Gestión de descartes — config.yaml

```yaml
descubrimiento:
  activo: true
  dia: "domingo"
  top_n: 15
  descartados:        # tickers que el usuario ya estudió y descartó: no repetir ruido
    - { ticker: "XYZ", motivo: "modelo de negocio que no entiendo", fecha: "2026-06-15" }
  min_score_aviso: 70 # solo avisar por Telegram si alguna nueva supera este score
```

El campo `descartados` es importante para el método: estudiar y descartar es trabajo
valioso — el sistema debe recordarlo para no re-proponer lo mismo cada semana.

### 5. Tests

`tests/test_descubrimiento.py` (sin red, con datos sintéticos):
(a) exclusión de watchlist y descartados funciona; (b) el top N ordena por score;
(c) la reanudación tras aborto retoma donde se quedó; (d) el informe .md se genera
con el aviso fijo en cabecera.

**Hecho cuando:** los tests pasan, una pasada real completa termina sin baneos de
yfinance (verificar en el log que las pausas se respetaron) y el informe .md del
domingo lista 15 candidatas con sus scores, ninguna de ellas de la watchlist.

### Advertencias de uso (para el README de la fase)

- El top 15 semanal mostrará sesgos sistemáticos del score (favorece GAAP limpio:
  saldrán aseguradoras, industriales maduras...; penaliza compounders con SBC alta,
  como se vio con AXON 50/100). Es una característica conocida, no un bug: el score
  filtra perfiles, el usuario aporta el contexto.
- Universo limitado a renta variable USA (S&P 500+400). Ampliable en el futuro, pero
  empezar acotado.
- La métrica de éxito de esta fase NO es "encontrar la próxima joya", sino alimentar
  el embudo de estudio del usuario con 2-3 candidatas interesantes al mes.
