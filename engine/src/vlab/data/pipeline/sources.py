"""Registry of the public raw inputs and their download logic."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path

from vlab.data.pipeline.common import log, sha256_file


@dataclass(frozen=True)
class Source:
    """A raw input: where it comes from, under which licence and where it lands."""

    key: str
    filename: str
    urls: tuple[str, ...]
    licence: str
    description: str
    reference: str
    landing_page: str = ""
    extra: dict[str, str] = field(default_factory=dict)


SOURCES: dict[str, Source] = {
    s.key: s
    for s in (
        Source(
            key="gtfs",
            filename="gtfs_tuc_pamplona.zip",
            urls=(),  # committed; obtained from Spain's National Access Point (feed 1177)
            licence="Open data, National Access Point for multimodal transport (NAP Spain)",
            description="Official GTFS of TUC Pamplona (Mancomunidad de la Comarca de Pamplona)",
            reference="service 2026-11-10 to 2026-11-30",
            landing_page="https://nap.transportes.gob.es/Files/Detail/1177",
        ),
        Source(
            key="osm",
            filename="osm/navarra-latest.osm.pbf",
            urls=(
                "https://download.openstreetmap.fr/extracts/europe/spain/"
                "comunidad_foral_de_navarra-latest.osm.pbf",
                # Fallback (not reachable from the original build environment).
                "https://download.geofabrik.de/europe/spain/navarra-latest.osm.pbf",
            ),
            licence="ODbL 1.0 (c) OpenStreetMap contributors",
            description="OpenStreetMap extract of the Comunidad Foral de Navarra",
            reference="daily extract, retrieval date",
            landing_page="https://download.openstreetmap.fr/extracts/europe/spain/",
        ),
        Source(
            key="ine_sections",
            filename="ine/seccionado_2025.zip",
            urls=("https://www.ine.es/prodyser/cartografia/seccionado_2025.zip",),
            licence="INE terms of use: free reuse citing INE as the source (ine.es Aviso legal)",
            description="INE census-section boundaries (seccionado) at 2025-01-01, ETRS89 UTM30",
            reference="2025-01-01",
            landing_page="https://www.ine.es/ss/Satellite?c=Page&cid=1259952026632&pagename=ProductosYServicios%2FPYSLayout",
        ),
        Source(
            key="ine_adrh_income",
            filename="ine/adrh_navarra_income_31124.csv",
            urls=("https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/31124.csv",),
            licence="INE terms of use: free reuse citing INE as the source (ine.es Aviso legal)",
            description=(
                "INE Atlas de distribucion de renta de los hogares (ADRH), Navarra: "
                "mean and median income indicators by municipality, district and section "
                "(table 31124)"
            ),
            reference="income year 2024 (sections as of 2025-01-01)",
            landing_page="https://www.ine.es/jaxiT3/Tabla.htm?t=31124",
        ),
        Source(
            key="ine_adrh_demography",
            filename="ine/adrh_navarra_demography_31132.csv",
            urls=("https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/31132.csv",),
            licence="INE terms of use: free reuse citing INE as the source (ine.es Aviso legal)",
            description=(
                "INE ADRH, Navarra: demographic indicators by section, including resident "
                "population (table 31132)"
            ),
            reference="2024 (sections as of 2025-01-01)",
            landing_page="https://www.ine.es/jaxiT3/Tabla.htm?t=31132",
        ),
    )
}


def download(source: Source, raw_dir: Path, *, force: bool = False, retries: int = 3) -> Path:
    """Download ``source`` into ``raw_dir`` (skipped when present unless ``force``).

    Tries every URL in order; writes atomically through a ``.part`` file.
    """
    import requests  # pipeline-only dependency

    dest = raw_dir / source.filename
    if dest.exists() and dest.stat().st_size > 0 and not force:
        log.info("  %s: cached (%s)", source.key, dest.relative_to(raw_dir))
        return dest
    if not source.urls:
        if dest.exists():
            return dest
        raise FileNotFoundError(f"{dest} is missing and has no download URL ({source.landing_page})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in source.urls:
        for attempt in range(1, retries + 1):
            try:
                log.info("  %s: downloading %s (attempt %d)", source.key, url, attempt)
                with requests.get(url, stream=True, timeout=(20, 300)) as r:
                    r.raise_for_status()
                    part = dest.with_suffix(dest.suffix + ".part")
                    with part.open("wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                if part.stat().st_size == 0:
                    raise OSError("empty response")
                part.replace(dest)
                log.info("  %s: %.1f MB", source.key, dest.stat().st_size / 1e6)
                return dest
            except Exception as exc:  # network errors are retried, then the next URL
                errors.append(f"{url}: {exc}")
                time.sleep(2 * attempt)
    raise RuntimeError(f"could not download {source.key}:\n  " + "\n  ".join(errors))


def describe(source: Source, path: Path) -> dict[str, object]:
    """Manifest entry for a raw input."""
    stat = path.stat()
    return {
        "key": source.key,
        "file": f"data/raw/{source.filename}",
        "urls": list(source.urls),
        "landing_page": source.landing_page,
        "licence": source.licence,
        "description": source.description,
        "reference": source.reference,
        "retrieved": dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.UTC).strftime("%Y-%m-%d"),
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
    }
