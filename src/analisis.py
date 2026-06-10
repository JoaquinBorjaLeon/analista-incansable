"""M2: score fundamental — checklist del §5 del SPEC codificado.

Score 0-100 con pesos y umbrales desde config.yaml. Verde = puntos completos,
amarillo = mitad, rojo o dato ausente = 0. Las métricas ausentes se muestran
como "s/d": nunca se inventa ni se interpola un dato.

Las banderas rojas se listan SIEMPRE junto al score (no se promedian) y la
nota_manual del ticker se imprime siempre. Nunca emite "comprar/vender".

CLI: python -m src.analisis [TICKER ...]
     Sin argumentos procesa watchlist + secundarios del config.
"""

import json
import logging
import sys
from datetime import date

from . import db

log = logging.getLogger("analisis")

ICONOS = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴", "s/d": "⚪"}


def _fmt_pct(v):
    return "s/d" if v is None else f"{v:.1f}%"


def _fmt_musd(v):
    return "s/d" if v is None else f"{v / 1e6:,.0f} M USD"


def _puntos(estado, peso):
    if estado == "verde":
        return peso
    if estado == "amarillo":
        return peso / 2
    return 0


def calcular_score(metricas: dict, config: dict, bandera_manual: str | None = None) -> dict:
    """Aplica la tabla del §5. Devuelve {score_total, desglose, banderas}."""
    u = config["umbrales_score"]
    p = config["pesos_score"]
    m = metricas
    desglose = []

    def criterio(nombre, estado, valor, peso):
        desglose.append({
            "criterio": nombre, "estado": estado, "valor": valor,
            "puntos": _puntos(estado, peso), "max": peso,
        })

    def semaforo(valor, verde, amarillo):
        if valor is None:
            return "s/d"
        if valor > verde:
            return "verde"
        if valor >= amarillo:
            return "amarillo"
        return "rojo"

    # 1. Crecimiento: ingresos YoY
    crec = m.get("crecimiento_ingresos_yoy")
    criterio("Crecimiento ingresos YoY",
             semaforo(crec, u["crecimiento_verde"], u["crecimiento_amarillo"]),
             _fmt_pct(crec), p["crecimiento"])

    # 2. Calidad de margen: margen bruto
    mb = m.get("margen_bruto")
    criterio("Margen bruto",
             semaforo(mb, u["margen_bruto_verde"], u["margen_bruto_amarillo"]),
             _fmt_pct(mb), p["margen_bruto"])

    # 3. Rentabilidad real: FCF > 0 y creciente (verde) / > 0 estable (amarillo)
    fcf, fcf_ant = m.get("fcf_ttm"), m.get("fcf_anterior")
    if fcf is None:
        estado_fcf = "s/d"
    elif fcf > 0 and fcf_ant is not None and fcf > fcf_ant:
        estado_fcf = "verde"
    elif fcf > 0:
        estado_fcf = "amarillo"
    else:
        estado_fcf = "rojo"
    criterio("FCF TTM", estado_fcf, _fmt_musd(fcf), p["fcf"])

    # 4. Conversión: margen FCF
    mfcf = m.get("margen_fcf")
    criterio("Margen FCF",
             semaforo(mfcf, u["margen_fcf_verde"], u["margen_fcf_amarillo"]),
             _fmt_pct(mfcf), p["margen_fcf"])

    # 5. Balance: deuda neta/EBITDA (caja neta cuenta como verde)
    deuda, caja = m.get("deuda_total"), m.get("caja")
    deuda_neta = deuda - caja if (deuda is not None and caja is not None) else None
    dne = m.get("deuda_neta_ebitda")
    if deuda_neta is not None and deuda_neta <= 0:
        estado_bal, valor_bal = "verde", "caja neta"
    elif dne is None:
        estado_bal, valor_bal = "s/d", "s/d"
    elif dne < u["deuda_ebitda_verde"]:
        estado_bal, valor_bal = "verde", f"{dne:.1f}x"
    elif dne <= u["deuda_ebitda_amarillo"]:
        estado_bal, valor_bal = "amarillo", f"{dne:.1f}x"
    else:
        estado_bal, valor_bal = "rojo", f"{dne:.1f}x"
    criterio("Deuda neta/EBITDA", estado_bal, valor_bal, p["balance"])

    # 6. Retorno: ROE
    roe = m.get("roe")
    criterio("ROE", semaforo(roe, u["roe_verde"], u["roe_amarillo"]), _fmt_pct(roe), p["roe"])

    # 7. Dilución: crecimiento de acciones YoY (menos es mejor)
    dil = m.get("dilucion_yoy")
    if dil is None:
        estado_dil = "s/d"
    elif dil < u["dilucion_verde"]:
        estado_dil = "verde"
    elif dil <= u["dilucion_amarillo"]:
        estado_dil = "amarillo"
    else:
        estado_dil = "rojo"
    criterio("Dilución acciones YoY", estado_dil, _fmt_pct(dil), p["dilucion"])

    # 8. Beneficio acompaña: crec. beneficio ≥ crec. ingresos (verde);
    #    beneficio > 0 pero crece menos (amarillo)
    ben = m.get("beneficio_neto")
    crec_ben = m.get("crecimiento_beneficio_yoy")
    if ben is None:
        estado_ben, valor_ben = "s/d", "s/d"
    elif ben > 0 and crec_ben is not None and crec is not None and crec_ben >= crec:
        estado_ben, valor_ben = "verde", f"benef. {_fmt_pct(crec_ben)} vs ingresos {_fmt_pct(crec)}"
    elif ben > 0:
        estado_ben, valor_ben = "amarillo", f"benef. {_fmt_pct(crec_ben)} vs ingresos {_fmt_pct(crec)}"
    else:
        estado_ben, valor_ben = "rojo", "pérdidas"
    criterio("Beneficio acompaña", estado_ben, valor_ben, p["beneficio_acompana"])

    # Banderas rojas (§5): se listan siempre, no se promedian
    banderas = []
    if dil is not None and dil > u["dilucion_maxima"]:
        banderas.append(f"🚩 Dilución > {u['dilucion_maxima']}% anual ({_fmt_pct(dil)})")
    if fcf is not None and fcf < 0:
        banderas.append(f"🚩 FCF negativo ({_fmt_musd(fcf)})")
    mb_ant = m.get("margen_bruto_anterior")
    if mb is not None and mb_ant is not None and (mb_ant - mb) > u["caida_margen_bruto_pp"]:
        banderas.append(
            f"🚩 Margen bruto en caída > {u['caida_margen_bruto_pp']} p.p. YoY ({mb_ant:.1f}% → {mb:.1f}%)"
        )
    if dne is not None and dne > u["deuda_ebitda_bandera"]:
        banderas.append(f"🚩 Deuda neta/EBITDA > {u['deuda_ebitda_bandera']}x ({dne:.1f}x)")
    crec_ant = m.get("crecimiento_ingresos_yoy_anterior")
    if crec is not None and crec_ant is not None and (crec_ant - crec) > u["deceleracion_ingresos_pp"]:
        banderas.append(
            f"🚩 Crecimiento decelerando > {u['deceleracion_ingresos_pp']} p.p. "
            f"({crec_ant:.1f}% → {crec:.1f}%)"
        )
    if bandera_manual:
        banderas.append(f"🚩 Manual: {bandera_manual}")

    return {
        "score_total": sum(c["puntos"] for c in desglose),
        "desglose": desglose,
        "banderas": banderas,
    }


def formatear_score(ticker: str, score_total: float, detalle: dict) -> str:
    """Score + desglose + banderas + nota_manual. Nunca un 'comprar/vender'."""
    lineas = [f"{ticker} — Score {score_total:g}/100"]
    for c in detalle["desglose"]:
        icono = ICONOS.get(c["estado"], "⚪")
        lineas.append(f"  {icono} {c['criterio']:<26} {c['valor']:<34} {c['puntos']:g}/{c['max']}")
    if detalle["banderas"]:
        lineas.extend(f"  {b}" for b in detalle["banderas"])
    else:
        lineas.append("  Sin banderas rojas")
    if detalle.get("nota_manual"):
        lineas.append(f"  Nota: {detalle['nota_manual']}")
    return "\n".join(lineas)


def procesar_ticker(con, ticker: str, config: dict):
    """Descarga fundamentales, guarda snapshot, calcula y guarda el score."""
    from . import ingesta  # import perezoso: evita ciclo ingesta ↔ analisis

    metricas = ingesta.descargar_fundamentales(ticker)
    hoy = date.today().isoformat()
    db.upsert_fundamentales(con, ticker, hoy, metricas)

    datos = ((config.get("watchlist") or {}).get(ticker)
             or (config.get("secundarios") or {}).get(ticker) or {})
    resultado = calcular_score(metricas, config, datos.get("bandera_manual"))
    detalle = {
        "desglose": resultado["desglose"],
        "banderas": resultado["banderas"],
        "nota_manual": datos.get("nota_manual"),
    }
    db.upsert_score(con, ticker, hoy, resultado["score_total"],
                    json.dumps(detalle, ensure_ascii=False))
    return resultado["score_total"], detalle


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    from . import ingesta

    config = ingesta.cargar_config()
    tickers = sys.argv[1:] or list(
        {**config["watchlist"], **(config.get("secundarios") or {})}
    )
    con = db.conectar()
    try:
        for ticker in tickers:
            try:
                score, detalle = procesar_ticker(con, ticker, config)
                print(formatear_score(ticker, score, detalle))
                print()
            except Exception:
                log.exception("%s: fallo al calcular el score, se continúa", ticker)
    finally:
        con.close()


if __name__ == "__main__":
    main()
