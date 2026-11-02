"""M3b: titulares recientes por ticker (yfinance `Ticker.news`).

Responde a la pregunta "¿por qué se ha movido?" antes de mirar una zona de entrada.
Si yfinance falla o cambia el formato, devuelve una lista vacía: una alerta sin
titulares es mejor que una alerta que no llega.

CLI: python -m src.titulares TICKER [N]
"""

import logging
import sys

log = logging.getLogger("titulares")


def _normalizar(item: dict) -> dict | None:
    """Acepta el formato antiguo (title/publisher/link) y el nuevo (content.*) de yfinance."""
    if not isinstance(item, dict):
        return None
    contenido = item.get("content") if isinstance(item.get("content"), dict) else item
    titulo = contenido.get("title")
    if not titulo:
        return None
    proveedor = contenido.get("provider")
    fuente = proveedor.get("displayName") if isinstance(proveedor, dict) else contenido.get("publisher")
    enlace = contenido.get("canonicalUrl") or contenido.get("clickThroughUrl")
    url = enlace.get("url") if isinstance(enlace, dict) else contenido.get("link")
    fecha = contenido.get("pubDate") or contenido.get("providerPublishTime")
    return {"titulo": titulo.strip(), "fuente": fuente or "", "url": url or "", "fecha": fecha}


def obtener_titulares(ticker: str, n: int = 5, cliente=None) -> list[dict]:
    """Últimos `n` titulares de un ticker. Nunca lanza: ante cualquier fallo devuelve []."""
    try:
        if cliente is None:
            import yfinance as yf
            cliente = yf.Ticker(ticker)
        noticias = cliente.news or []
    except Exception as error:
        log.warning("%s: no se pudieron obtener titulares (%s)", ticker, type(error).__name__)
        return []
    titulares = []
    for item in noticias:
        normalizado = _normalizar(item)
        if normalizado:
            titulares.append(normalizado)
        if len(titulares) >= n:
            break
    return titulares


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("Uso: python -m src.titulares TICKER [N]")
        sys.exit(1)
    ticker = sys.argv[1].upper()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    for t in obtener_titulares(ticker, n):
        print(f"- {t['titulo']} ({t['fuente']})")


if __name__ == "__main__":
    main()
