"""INE census sections, population and household income (ADRH)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry.base import BaseGeometry

from vlab.data.pipeline.common import UTM30, log

NAVARRA = "31"
ADRH_YEAR = 2024
INCOME_PER_CAPITA = "Renta neta media por persona"
INCOME_PER_HOUSEHOLD = "Renta neta media por hogar"
POPULATION = "Población"


def _spanish_number(s: pd.Series) -> pd.Series:
    """Parse INE csv numbers ("206.464", "50,2"; "." and "" mean missing)."""
    t = s.astype("string").str.strip().replace({".": pd.NA, "": pd.NA, '""': pd.NA})
    t = t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(t, errors="coerce")


def _read_adrh(path: Path, indicator_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    expected = {"Municipios", "Distritos", "Secciones", indicator_col, "Periodo", "Total"}
    if missing := expected - set(df.columns):
        raise ValueError(f"{path.name}: unexpected ADRH layout, missing columns {missing}")
    df = df[df["Secciones"].str.len() > 0].copy()
    df["section_id"] = df["Secciones"].str.slice(0, 10)
    df["year"] = pd.to_numeric(df["Periodo"], errors="coerce")
    df["value"] = _spanish_number(df["Total"])
    return df.rename(columns={indicator_col: "indicator"})[
        ["section_id", "indicator", "year", "value"]
    ]


def read_section_population(path: Path, year: int = ADRH_YEAR) -> pd.Series:
    """Resident population per section (ADRH demographic indicators, INE table 31132)."""
    df = _read_adrh(path, "Indicadores demográficos")
    df = df[(df["indicator"] == POPULATION) & (df["year"] == year)]
    s = df.set_index("section_id")["value"]
    if s.index.has_duplicates:
        raise ValueError("duplicate sections in ADRH population table")
    return s.rename("population")


def read_section_income(path: Path, year: int = ADRH_YEAR) -> pd.DataFrame:
    """Net mean income per person and per household (EUR/year), INE table 31124."""
    df = _read_adrh(path, "Indicadores de renta media y mediana")
    df = df[df["year"] == year]
    wide = df.pivot_table(index="section_id", columns="indicator", values="value", aggfunc="first")
    return pd.DataFrame(
        {
            "income_per_capita": wide.get(INCOME_PER_CAPITA),
            "income_per_household": wide.get(INCOME_PER_HOUSEHOLD),
        }
    )


def read_sections(zip_path: Path, extract_dir: Path) -> gpd.GeoDataFrame:
    """Navarra census sections from the INE seccionado zip (EPSG:25830)."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    shp: Path | None = None
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name  # flatten (the 2025 zip has a non-ASCII folder)
            if not name or info.is_dir():
                continue
            target = extract_dir / name
            if not target.exists() or target.stat().st_size != info.file_size:
                target.write_bytes(zf.read(info))
            if name.lower().endswith(".shp"):
                shp = target
    if shp is None:
        raise ValueError(f"no shapefile in {zip_path}")
    gdf = gpd.read_file(shp, where=f"CPRO='{NAVARRA}'")
    if gdf.crs is None or gdf.crs.to_epsg() != 25830:
        gdf = gdf.to_crs(UTM30)
    return gdf[["CUSEC", "CUMUN", "NMUN", "geometry"]].rename(
        columns={"CUSEC": "section_id", "CUMUN": "municipality_code", "NMUN": "municipality"}
    )


def build_sections(
    sections_zip: Path,
    extract_dir: Path,
    population_csv: Path,
    income_csv: Path,
    study_area: BaseGeometry,
) -> gpd.GeoDataFrame:
    """Sections intersecting the study area with population and income (EPSG:25830)."""
    sec = read_sections(sections_zip, extract_dir)
    sec = sec[sec.intersects(study_area)].copy()
    pop = read_section_population(population_csv)
    inc = read_section_income(income_csv)
    sec = sec.join(pop, on="section_id").join(inc, on="section_id")
    missing = sec["population"].isna()
    if missing.any():
        raise ValueError(
            f"sections without ADRH population: {sec.loc[missing, 'section_id'].tolist()}"
        )
    sec["population"] = sec["population"].round().astype(np.int64)
    n_inc = int(sec["income_per_capita"].isna().sum())
    log.info(
        "  sections: %d intersect the study area, population %d, %d without income",
        len(sec), int(sec["population"].sum()), n_inc,
    )  # fmt: skip
    return sec.sort_values("section_id").reset_index(drop=True)
