# ANEXO al SPEC — Fases 2.5 y 6

> Este documento amplía `SPEC_analizador_inversiones.md`. Mismas reglas: una fase por
> sesión, criterio de "hecho" antes de avanzar, la herramienta analiza y NO decide.
> Orden recomendado de implementación: Fase 3 → Fase 2.5 → Fase 4 → Fase 6 → (Fase 5 opcional).

---

## FASE 2.5 — Informe de tesis por ticker (2-4 días) · 📍 Mini PC

**Objetivo:** unir en una sola vista todo lo que el sistema sabe de un ticker
(score + zona + tesis cualitativa + banderas), de forma que la pregunta "¿por qué sí /
por qué no entrar?" tenga respuesta estructurada. El sistema presenta condiciones y
argumentos; NUNCA emite una recomendación de compra/venta.

### 1. Ampliar `config.yaml` — estructura de tesis por ticker

Añadir a cada ticker de `watchlist` un bloque `tesis` con este esquema:

```yaml
ZETA:
  zona_entrada: [18.5, 19.5]
  # ... campos existentes ...
  tesis:
    por_que_si:
      - "Crecimiento orgánico ~30% con inflexión a rentabilidad GAAP guiada para 2026"
      - "FCF positivo y creciente (~200M+ TTM) con caja neta"
      - "Foso de datos: SuperGraph/Data Cloud propietaria + Athena con tracción real"
    por_que_no:
      - "Litigio de valores vivo (Davoodi, SDNY): cola binaria que ningún stop cubre"
      - "Rentabilidad GAAP aún fina y dependiente de la SBC"
      - "Sector MarTech muy competido (Salesforce, Adobe, TTD)"
    condiciones_entrada:
      - "Precio dentro de zona 18.5-19.5 (o ruptura confirmada >24.90)"
      - "Sin noticia negativa nueva del litigio en los últimos 30 días"
      - "Crecimiento orgánico del último trimestre >= 20%"
    invalidantes:   # si ocurre cualquiera, la tesis se revisa entera
      - "Fallo judicial adverso o nueva acusación con evidencia"
      - "Crecimiento orgánico < 20% dos trimestres seguidos"
      - "FCF TTM negativo"
    tamano: "PEQUEÑO — la cola del litigio domina el dimensionamiento (fórmula Paso 1)"
    revisada: "2026-06-10"   # fecha de última revisión manual de la tesis
```

Rellenar el bloque `tesis` de los 4 tickers principales con el contenido que el usuario
ya tiene definido (ZETA arriba como ejemplo completo; para MGNI, AXON y PGY usar las
notas existentes como punto de partida y dejar TODO claros donde falte contenido — el
usuario los completará, la tesis es SUYA, no del código).

### 2. Nuevo módulo `src/tesis.py`

CLI: `python -m src.tesis ZETA` imprime el informe completo de un ticker:

```
═══ ZETA — Informe de tesis (tesis revisada: 2026-06-10) ═══

PRECIO Y ZONA
  Cierre: 21.76 | Zona: 18.5-19.5 (+11.6%) | RSI 58.2 | vs SMA200 +16.3%

SCORE FUNDAMENTAL: 75/100
  [desglose de criterios como en src.analisis]

POR QUÉ SÍ                          POR QUÉ NO
  • ...                               • ...

CONDICIONES DE ENTRADA              [estado]
  • Precio en zona                    ✗ (a +11.6%)
  • Sin noticia litigio 30d           ? (verificar manualmente)
  • Crecimiento >= 20%                ✓ (29.7%)

INVALIDANTES VIGILADOS
  • FCF TTM negativo                  ✓ OK (FCF +255M)
  • Crecimiento < 20% x2 trimestres   ✓ OK
  • Fallo judicial                    ? manual

TAMAÑO: PEQUEÑO — cola de litigio
🚩 BANDERAS: Manual: Litigio de valores vivo
⚠️  Esta es una síntesis informativa. La decisión de entrada es del usuario.
```

Reglas de evaluación de condiciones/invalidantes:
- Las que se puedan comprobar con datos del sistema (precio en zona, crecimiento, FCF)
  se evalúan automáticamente: ✓ / ✗ con el valor actual.
- Las que requieran juicio o información externa (noticias del litigio, fallos
  judiciales) se marcan `? manual` — NUNCA evaluarlas automáticamente ni asumirlas OK.
- El parser debe ser tolerante: condiciones se escriben en lenguaje natural; detectar
  las automatizables por palabras clave sencillas (p. ej. "precio", "zona",
  "crecimiento", "FCF") y dejar el resto como manuales. Documentar el mapeo en el código.

### 3. Integración con el informe diario

`src/informe.py`: añadir al final una línea por ticker con el resumen de condiciones:
`ZETA: 1/3 condiciones ✓, 2 manuales pendientes — tesis revisada hace 0 días`.
Si una tesis lleva > 90 días sin revisar (`revisada`), avisar: "⚠️ tesis caducada, revisar".

### 4. Tests

`tests/test_tesis.py`: con config sintética — (a) condición automatizable que pasa,
(b) que no pasa, (c) condición manual queda en `?`, (d) tesis caducada genera aviso.

**Hecho cuando:** los tests pasan y `python -m src.tesis ZETA` muestra el informe
completo con las condiciones bien clasificadas (automáticas evaluadas, manuales en `?`).

---

## FASE 6 — Panel web para el móvil (1-2 semanas) · 📍 Mini PC + móvil

**Objetivo:** dashboard web servido desde el Mini PC, accesible desde el móvil vía
Tailscale, con la información de Fases 1-2.5. Solo lectura: el panel NO permite editar
tesis ni zonas (eso se hace en config.yaml versionado en git).

### Prerequisitos
1. Tailscale instalado en el móvil (app oficial Android/iOS) y sesión iniciada en la
   misma tailnet. Verificar que `http://<ip-privada-del-servidor>:8888` (Jupyter) abre desde el
   móvil antes de empezar — si Jupyter abre, la red está lista.
2. `pip install fastapi uvicorn jinja2` en el venv del proyecto.

### Puerto y servicio
- Puerto **8080** (libre según §0 del SPEC; no tocar 3000/5678/6333/8888).
- Servicio systemd `panel-inversiones.service` (usuario <usuario>, WorkingDirectory
  el proyecto, ExecStart con uvicorn, Restart=always) para que sobreviva reinicios.
- Escuchar en `0.0.0.0:8080` — queda protegido porque la red solo es alcanzable
  dentro de la tailnet. NO configurar port-forwarding en el router ni túneles públicos.

### Estructura

```
panel/
├── app.py            # FastAPI: rutas / (dashboard) y /ticker/{symbol}
├── templates/
│   ├── index.html    # tabla resumen: ticker, cierre, distancia a zona, score, banderas
│   └── ticker.html   # vista detalle = informe de tesis de la Fase 2.5 en HTML
└── static/style.css  # CSS simple, mobile-first (el 90% del uso será desde el móvil)
```

### Contenido
- **Dashboard (`/`):** una tarjeta/fila por ticker de la watchlist: cierre, distancia a
  zona (color: verde si EN ZONA, ámbar si <3%, gris resto), score /100, nº de banderas 🚩,
  fecha del último dato. Ordenado por distancia a zona ascendente.
- **Detalle (`/ticker/ZETA`):** el informe de la Fase 2.5 completo en HTML legible en
  pantalla de móvil (una columna, tipografía grande).
- Pie de página fijo en TODAS las vistas: "Herramienta de análisis personal. No es una
  recomendación de inversión."
- Datos: leer de SQLite y config.yaml directamente (sin API intermedia). Refresco al
  recargar la página — no hace falta tiempo real (los datos son diarios).

### Seguridad (innegociable)
- Accesible SOLO vía tailnet. Ningún puerto expuesto a internet, ningún túnel
  (Cloudflare u otro) hacia este servicio.
- El panel es de solo lectura; no hay formularios ni endpoints de escritura.

### Tests / Hecho cuando
1. `systemctl status panel-inversiones` → active (running), y sobrevive a un reinicio
   del Mini PC.
2. Desde el móvil (con Tailscale activo, datos móviles — NO el wifi de casa, para
   probar acceso remoto real): `http://<ip-privada-del-servidor>:8080` muestra el dashboard y
   el detalle de ZETA se lee cómodamente.
3. Desde un dispositivo FUERA de la tailnet, el puerto no es alcanzable.

### Extensiones futuras (NO implementar ahora; anotadas para no perderlas)
- Gráfico de precio con la zona sombreada (matplotlib estático o chart.js).
- Histórico de scores para ver evolución (la tabla `scores` ya guarda histórico).
- Botón "marcar tesis como revisada hoy" (rompería el solo-lectura: decidir entonces).
