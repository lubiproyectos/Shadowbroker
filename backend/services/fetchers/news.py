"""News fetching, geocoding, clustering, and risk assessment."""
import re
import json
import logging
import concurrent.futures
import requests
import os
import httpx
import time
from collections import OrderedDict
import feedparser
from dotenv import load_dotenv
from services.network_utils import fetch_with_curl
from services.fetchers._store import latest_data, _data_lock, _mark_fresh
from services.fetchers.retry import with_retry
from services.metrics_store import record_usage, record_error
from services.metrics_store import get_metrics

# Cargar .env con override=True para recoger claves añadidas tras el arranque
load_dotenv(override=True)

logger = logging.getLogger("services.data_fetcher")


# Keyword -> coordinate mapping for geocoding news articles
_KEYWORD_COORDS = {
    "venezuela": (7.119, -66.589),
    "brazil": (-14.235, -51.925),
    "argentina": (-38.416, -63.616),
    "colombia": (4.570, -74.297),
    "mexico": (23.634, -102.552),
    "united states": (38.907, -77.036),
    " usa ": (38.907, -77.036),
    " us ": (38.907, -77.036),
    "washington": (38.907, -77.036),
    "canada": (56.130, -106.346),
    "ukraine": (49.487, 31.272),
    "kyiv": (50.450, 30.523),
    "russia": (61.524, 105.318),
    "moscow": (55.755, 37.617),
    "israel": (31.046, 34.851),
    "gaza": (31.416, 34.333),
    "iran": (32.427, 53.688),
    "lebanon": (33.854, 35.862),
    "syria": (34.802, 38.996),
    "yemen": (15.552, 48.516),
    # East Asia — specific locations (longer keywords matched first via _SORTED_KEYWORDS)
    "taiwan strait": (24.0, 119.5),
    "south china sea": (15.0, 115.0),
    "east china sea": (28.0, 125.0),
    "philippine sea": (20.0, 130.0),
    "senkaku": (25.740, 123.474),
    "diaoyu": (25.740, 123.474),
    "ryukyu": (26.334, 127.800),
    "okinawa": (26.334, 127.800),
    "kadena": (26.351, 127.767),
    "naha": (26.212, 127.679),
    "yokosuka": (35.283, 139.671),
    "sasebo": (33.159, 129.722),
    "misawa": (40.682, 141.368),
    "iwakuni": (34.144, 132.236),
    "guam": (13.444, 144.793),
    "taipei": (25.033, 121.565),
    "kaohsiung": (22.616, 120.313),
    "xiamen": (24.479, 118.089),
    "fujian": (26.074, 119.296),
    "guangdong": (23.379, 113.763),
    "zhejiang": (29.141, 119.788),
    "hainan": (19.200, 109.999),
    "china": (35.861, 104.195),
    "beijing": (39.904, 116.407),
    "taiwan": (23.697, 120.960),
    "north korea": (40.339, 127.510),
    "south korea": (35.907, 127.766),
    "pyongyang": (39.039, 125.762),
    "seoul": (37.566, 126.978),
    "japan": (36.204, 138.252),
    "tokyo": (35.676, 139.650),
    "afghanistan": (33.939, 67.709),
    "pakistan": (30.375, 69.345),
    "india": (20.593, 78.962),
    " uk ": (55.378, -3.435),
    "london": (51.507, -0.127),
    "france": (46.227, 2.213),
    "paris": (48.856, 2.352),
    "germany": (51.165, 10.451),
    "berlin": (52.520, 13.405),
    "sudan": (12.862, 30.217),
    "congo": (-4.038, 21.758),
    "south africa": (-30.559, 22.937),
    "nigeria": (9.082, 8.675),
    "egypt": (26.820, 30.802),
    "zimbabwe": (-19.015, 29.154),
    "kenya": (-1.292, 36.821),
    "libya": (26.335, 17.228),
    "mali": (17.570, -3.996),
    "niger": (17.607, 8.081),
    "somalia": (5.152, 46.199),
    "ethiopia": (9.145, 40.489),
    "australia": (-25.274, 133.775),
    "middle east": (31.500, 34.800),
    "europe": (48.800, 2.300),
    "africa": (0.000, 25.000),
    "america": (38.900, -77.000),
    "south america": (-14.200, -51.900),
    "asia": (34.000, 100.000),
    "california": (36.778, -119.417),
    "texas": (31.968, -99.901),
    "florida": (27.994, -81.760),
    "new york": (40.712, -74.006),
    "virginia": (37.431, -78.656),
    "british columbia": (53.726, -127.647),
    "ontario": (51.253, -85.323),
    "quebec": (52.939, -73.549),
    "delhi": (28.704, 77.102),
    "new delhi": (28.613, 77.209),
    "mumbai": (19.076, 72.877),
    "shanghai": (31.230, 121.473),
    "hong kong": (22.319, 114.169),
    "istanbul": (41.008, 28.978),
    "dubai": (25.204, 55.270),
    "singapore": (1.352, 103.819),
    "bangkok": (13.756, 100.501),
    "jakarta": (-6.208, 106.845),
    # East Asia — islands, straits, and disputed areas
    "pratas": (20.71, 116.72),
    "dongsha": (20.71, 116.72),
    "kinmen": (24.45, 118.38),
    "matsu": (26.16, 119.94),
    "scarborough": (15.14, 117.77),
    "paracel": (16.50, 112.00),
    "spratly": (10.00, 114.00),
    "miyako strait": (24.78, 125.30),
    "bashi channel": (21.00, 121.50),
    "luzon strait": (20.50, 121.50),
    " dmz ": (38.00, 127.00),
    "yalu": (40.00, 124.40),
    "yongbyon": (39.80, 125.76),
    "wonsan": (39.18, 127.48),
    "busan": (35.18, 129.07),
}

# Immutable after module load — sort by descending keyword length so
# specific locations ("taiwan strait") match before generic ones ("taiwan")
_SORTED_KEYWORDS = sorted(_KEYWORD_COORDS.items(), key=lambda x: len(x[0]), reverse=True)

# Caché de traducciones en memoria
_TRANSLATION_CACHE: OrderedDict = OrderedDict()
_TRANSLATION_CACHE_MAX = 500
_TRANSLATION_CACHE_TTL = 604800  # 7 días
_TRANSLATION_CACHE_FILE = "/app/data/translation_cache.json"

# Caracteres típicos del español que indican que el texto ya no necesita traducción
_SPANISH_MARKERS = set("áéíóúüñ¿¡")

def _should_translate(text: str) -> bool:
    """Devuelve True si el texto parece estar en inglés y necesita traducción."""
    if not text or not text.strip():
        return False
    lower = text.lower()
    # Si contiene caracteres exclusivos del español, ya está traducido
    if any(c in _SPANISH_MARKERS for c in lower):
        return False
    return True

def _resolve_coords(text: str) -> tuple[float, float] | None:
    """Return (lat, lng) for the most specific keyword match, or None.

    Longer keywords are tried first. Space-padded keywords (" us ", " uk ")
    use substring matching on padded text; all others use word-boundary regex.
    """
    padded_text = f" {text} "
    for kw, coords in _SORTED_KEYWORDS:
        if kw.startswith(" ") or kw.endswith(" "):
            if kw in padded_text:
                return coords
        else:
            if re.search(r'\b' + re.escape(kw) + r'\b', text):
                return coords
    return None

def _cleanup_cache() -> None:
    """Elimina entradas expiradas de la caché en memoria."""
    now = time.time()
    expired = [
        text for text, item in _TRANSLATION_CACHE.items()
        if now - item["ts"] > _TRANSLATION_CACHE_TTL
    ]
    for text in expired:
        _TRANSLATION_CACHE.pop(text, None)

def _load_cache_from_disk() -> None:
    """Carga la caché persistente desde disco al arrancar."""
    try:
        if not os.path.exists(_TRANSLATION_CACHE_FILE):
            return

        with open(_TRANSLATION_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        now = time.time()
        for text, item in data.items():
            if now - item["ts"] <= _TRANSLATION_CACHE_TTL:
                _TRANSLATION_CACHE[text] = item

        # Reescribe el archivo ya depurado
        _save_cache_to_disk()

        logger.info(f"Caché de traducciones cargada: {len(_TRANSLATION_CACHE)} entradas")
    except Exception as e:
        logger.warning(f"No se pudo cargar caché de traducciones: {e}")


def _save_cache_to_disk() -> None:
    """Persiste la caché en disco."""
    try:
        _cleanup_cache()
        with open(_TRANSLATION_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(_TRANSLATION_CACHE), f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"No se pudo guardar caché de traducciones: {e}")


# Cargar caché persistente al importar el módulo
_load_cache_from_disk()


def _get_cached_translation(text: str) -> str | None:
    """Return cached translation if present and not expired."""
    item = _TRANSLATION_CACHE.get(text)
    if not item:
        return None
    if time.time() - item["ts"] > _TRANSLATION_CACHE_TTL:
        _TRANSLATION_CACHE.pop(text, None)
        return None
    _TRANSLATION_CACHE.move_to_end(text)
    return item["value"]


def _set_cached_translation(text: str, translated: str) -> None:
    """Store translation in bounded LRU-style cache."""
    _TRANSLATION_CACHE[text] = {"value": translated, "ts": time.time()}
    _TRANSLATION_CACHE.move_to_end(text)
    while len(_TRANSLATION_CACHE) > _TRANSLATION_CACHE_MAX:
        _TRANSLATION_CACHE.popitem(last=False)


def translate_titles_batch(texts: list[str]) -> dict[str, str]:
    """Traduce una lista de titulares en UNA sola llamada a Claude.

    Devuelve dict {texto_original: traducción}.
    Los textos ya cacheados no se envían a la API.
    """
    # Comprobar límite diario antes de llamar a la API
    metrics = get_metrics()
    if metrics.get("tokens_today", 0) >= 100000:
        logger.warning("Límite diario de tokens alcanzado — traducción pausada")
        return {text: text for text in texts}

    if not texts:
        return {}

    result = {}
    to_translate = []

    # Separar los que ya están en caché
    for text in texts:
        if not _should_translate(text):
            result[text] = text
            continue
        cached = _get_cached_translation(text)
        if cached is not None:
            result[text] = cached
        else:
            to_translate.append(text)

    if not to_translate:
        return result

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        for text in to_translate:
            result[text] = text
        return result

    # Construir prompt con todos los titulares numerados
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(to_translate))
    prompt = (
        "Translate the following numbered news headlines to Spanish. "
        "Return ONLY the translations, one per line, with the same number prefix. "
        "If a headline is already in Spanish, return it unchanged. "
        "Do not add any explanation or extra text.\n\n"
        f"{numbered}"
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()

        data = resp.json()

        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        record_usage(input_tokens, output_tokens)

        raw = data["content"][0]["text"].strip()

        # Parsear respuesta numerada
        translations = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r'^(\d+)\.\s*(.+)$', line)
            if match:
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(to_translate):
                    translations[to_translate[idx]] = match.group(2).strip()

        # Guardar en caché y resultado
        for text in to_translate:
            translated = translations.get(text, text)
            _set_cached_translation(text, translated)
            result[text] = translated

        _save_cache_to_disk()
        logger.info(f"Batch traducidos {len(to_translate)} titulares en 1 llamada a Claude")

    except (requests.RequestException, ValueError, KeyError) as e:
        record_error(str(e))
        logger.warning(f"Batch translation failed: {e}")
        for text in to_translate:
            result[text] = text

    return result

@with_retry(max_retries=1, base_delay=2)
def fetch_news():
    from services.news_feed_config import get_feeds
    feed_config = get_feeds()
    feeds = {f["name"]: f["url"] for f in feed_config}
    source_weights = {f["name"]: f["weight"] for f in feed_config}

    clusters = {}
    _cluster_grid = {}

    def _fetch_feed(item):
        source_name, url = item
        try:
            xml_data = fetch_with_curl(url, timeout=10).text
            return source_name, feedparser.parse(xml_data)
        except (requests.RequestException, ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
            logger.warning(f"Feed {source_name} failed: {e}")
            return source_name, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        feed_results = list(pool.map(_fetch_feed, feeds.items()))

    all_entries = []
    for source_name, feed in feed_results:
        if not feed:
            continue
        for entry in feed.entries[:5]:
            all_entries.append((source_name, entry))

    # Batch: traducir todos los titulares no cacheados en 1 llamada
    all_titles = [e.get('title', '') for _, e in all_entries]
    translations = translate_titles_batch(all_titles)

    for source_name, entry in all_entries:
        title_original = entry.get('title', '')
        summary = entry.get('summary', '')
        title = translations.get(title_original, title_original)

        _seismic_kw = ["earthquake", "seismic", "quake", "tremor", "magnitude", "richter"]
        _text_lower = (title_original + " " + summary).lower()
        if any(kw in _text_lower for kw in _seismic_kw):
            continue

        if source_name == "GDACS":
            alert_level = entry.get("gdacs_alertlevel", "Green")
            if alert_level == "Red": risk_score = 10
            elif alert_level == "Orange": risk_score = 7
            else: risk_score = 4
        else:
            risk_keywords = ['war', 'missile', 'strike', 'attack', 'crisis', 'tension', 'military', 'conflict', 'defense', 'clash', 'nuclear']
            text = (title_original + " " + summary).lower()

            risk_score = 1
            for kw in risk_keywords:
                if kw in text:
                    risk_score += 2
            risk_score = min(10, risk_score)

        lat, lng = None, None

        if 'georss_point' in entry:
            geo_parts = entry['georss_point'].split()
            if len(geo_parts) == 2:
                lat, lng = float(geo_parts[0]), float(geo_parts[1])
        elif 'where' in entry and hasattr(entry['where'], 'coordinates'):
            coords = entry['where'].coordinates
            lat, lng = coords[1], coords[0]

        if lat is None:
            text = (title_original + " " + summary).lower()
            result = _resolve_coords(text)
            if result:
                lat, lng = result

        if lat is not None:
            key = None
            cell_x, cell_y = int(lng // 4), int(lat // 4)
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    for ckey in _cluster_grid.get((cell_x + dx, cell_y + dy), []):
                        parts = ckey.split(",")
                        elat, elng = float(parts[0]), float(parts[1])
                        if ((lat - elat)**2 + (lng - elng)**2)**0.5 < 4.0:
                            key = ckey
                            break
                    if key:
                        break
                if key:
                    break
            if key is None:
                key = f"{lat},{lng}"
                _cluster_grid.setdefault((cell_x, cell_y), []).append(key)
        else:
            key = title_original

        if key not in clusters:
            clusters[key] = []

        clusters[key].append({
            "title": title,
            "title_original": title_original,
            "link": entry.get('link', ''),
            "published": entry.get('published', ''),
            "source": source_name,
            "risk_score": risk_score,
            "coords": [lat, lng] if lat is not None else None
        })

    news_items = []
    for key, articles in clusters.items():
        articles.sort(key=lambda x: (x['risk_score'], source_weights.get(x["source"], 0)), reverse=True)
        max_risk = articles[0]['risk_score']

        top_article = articles[0]
        news_items.append({
            "title": top_article["title"],
            "link": top_article["link"],
            "published": top_article["published"],
            "source": top_article["source"],
            "risk_score": max_risk,
            "coords": top_article["coords"],
            "cluster_count": len(articles),
            "articles": articles,
            "machine_assessment": None
        })

    news_items.sort(key=lambda x: x['risk_score'], reverse=True)
    with _data_lock:
        latest_data['news'] = news_items
    _mark_fresh("news")
