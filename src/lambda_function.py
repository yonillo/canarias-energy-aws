import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuración por sistema eléctrico insular de Canarias
# Incluye capacidad instalada aproximada (MW) eólica y solar por isla (datos REE / Gobierno de Canarias)
# para poder calcular el factor de capacidad en tiempo real junto al mix oficial de REData
ISLANDS_CONFIG = {
    "gran_canaria": {
        "name": "Gran Canaria",
        "lat": 27.8500,
        "lon": -15.4300,
        "ree_geo_id": 8749,
        "installed_wind_mw": 305.0,
        "installed_solar_mw": 115.0,
        "peak_demand_ref_mw": 530.0
    },
    "tenerife": {
        "name": "Tenerife",
        "lat": 28.0800,
        "lon": -16.5100,
        "ree_geo_id": 8748,
        "installed_wind_mw": 245.0,
        "installed_solar_mw": 150.0,
        "peak_demand_ref_mw": 560.0
    },
    "lanzarote_fuerteventura": {
        "name": "Lanzarote - Fuerteventura",
        "lat": 28.7000,
        "lon": -13.8600,
        "ree_geo_id": 8747,
        "installed_wind_mw": 85.0,
        "installed_solar_mw": 55.0,
        "peak_demand_ref_mw": 240.0
    },
    "la_palma": {
        "name": "La Palma",
        "lat": 28.6500,
        "lon": -17.7800,
        "ree_geo_id": 8751,
        "installed_wind_mw": 12.0,
        "installed_solar_mw": 8.0,
        "peak_demand_ref_mw": 45.0
    },
    "la_gomera": {
        "name": "La Gomera",
        "lat": 28.0900,
        "lon": -17.1100,
        "ree_geo_id": 8750,
        "installed_wind_mw": 12.0,
        "installed_solar_mw": 3.0,
        "peak_demand_ref_mw": 15.0
    },
    "el_hierro": {
        "name": "El Hierro (Gorona del Viento)",
        "lat": 27.7800,
        "lon": -17.9200,
        "ree_geo_id": 8752,
        "installed_wind_mw": 11.5,
        "installed_solar_mw": 1.0,
        "peak_demand_ref_mw": 8.5
    }
}

# Cache en memoria de la ejecución Lambda para no golpear 6 veces el endpoint general de REE
_REE_ARCHIPELAGO_CACHE: Optional[Dict[str, Any]] = None


def fetch_calima_and_air_quality(lat: float, lon: float) -> Dict[str, Any]:
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "pm10,pm2_5,dust,aerosol_optical_depth,european_aqi",
        "timezone": "Atlantic/Canary"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        current = response.json().get("current", {})
        
        pm10 = current.get("pm10", 0.0) or 0.0
        if pm10 < 45:
            calima_level = "LIMPIO"
        elif pm10 < 100:
            calima_level = "MODERADA"
        elif pm10 < 200:
            calima_level = "ALTA"
        else:
            calima_level = "EXTREMA"

        return {
            "pm10_ug_m3": pm10,
            "pm2_5_ug_m3": current.get("pm2_5"),
            "saharan_dust_ug_m3": current.get("dust"),
            "aerosol_optical_depth": current.get("aerosol_optical_depth"),
            "european_aqi": current.get("european_aqi"),
            "calima_status": calima_level
        }
    except Exception as e:
        logger.error(f"Error extrayendo datos de calima ({lat}, {lon}): {e}")
        return {}


def fetch_solar_and_wind(lat: float, lon: float) -> Dict[str, Any]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": (
            "temperature_2m,cloud_cover,wind_speed_10m,wind_direction_10m,"
            "shortwave_radiation,direct_radiation,diffuse_radiation"
        ),
        "hourly": "wind_speed_80m",
        "forecast_days": 1,
        "timezone": "Atlantic/Canary"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        current = data.get("current", {})
        hourly_wind_80m = data.get("hourly", {}).get("wind_speed_80m", [None])[0]

        ghi = current.get("shortwave_radiation", 0.0) or 0.0
        diffuse = current.get("diffuse_radiation", 0.0) or 0.0
        diffuse_ratio = round(diffuse / ghi, 3) if ghi > 10 else 0.0

        return {
            "temp_c": current.get("temperature_2m"),
            "cloud_cover_pct": current.get("cloud_cover"),
            "wind_speed_10m_kmh": current.get("wind_speed_10m"),
            "wind_speed_80m_kmh": hourly_wind_80m,
            "wind_dir_deg": current.get("wind_direction_10m"),
            "solar_ghi_w_m2": ghi,
            "solar_direct_w_m2": current.get("direct_radiation"),
            "solar_diffuse_w_m2": diffuse,
            "solar_diffuse_ratio": diffuse_ratio
        }
    except Exception as e:
        logger.error(f"Error extrayendo datos solares/viento ({lat}, {lon}): {e}")
        return {}


def fetch_ree_canarias_official() -> Dict[str, Any]:
    """
    Consulta el endpoint oficial de REData (apidatos.ree.es) con los parámetros
    exactos que acepta para la CCAA de Canarias (geo_limit=ccaa, geo_ids=8742)
    usando una ventana segura de días cerrados para evitar el Error 500 de REE.
    """
    global _REE_ARCHIPELAGO_CACHE
    if _REE_ARCHIPELAGO_CACHE is not None:
        return _REE_ARCHIPELAGO_CACHE

    # REData consolida Canarias con 24-48h de decalaje: pedimos de hace 5 días a hace 1 día
    end_date = datetime.now() - timedelta(days=1)
    start_date = end_date - timedelta(days=4)

    url = "https://apidatos.ree.es/es/datos/generacion/estructura-generacion"
    params = {
        "start_date": start_date.strftime("%Y-%m-%dT00:00"),
        "end_date": end_date.strftime("%Y-%m-%dT23:59"),
        "time_trunc": "day",
        "geo_limit": "ccaa",
        "geo_ids": 8742
    }
    headers = {
        "Accept": "application/json",
        "User-Agent": "CanariasEnergyMonitor/1.0"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=12)
        response.raise_for_status()
        included = response.json().get("included", [])
        
        mix = {}
        for item in included:
            title = item.get("attributes", {}).get("title", "Otro")
            values = item.get("attributes", {}).get("values", [])
            if values:
                last = values[-1]
                mix[title] = {
                    "mwh_day": round(last.get("value", 0.0), 2),
                    "share_pct": round(last.get("percentage", 0.0) * 100, 2),
                    "consolidated_date": last.get("datetime", "")[:10]
                }
        _REE_ARCHIPELAGO_CACHE = mix
        return mix
    except Exception as e:
        logger.warning(f"Aviso en consulta REData Canarias: {e}")
        _REE_ARCHIPELAGO_CACHE = {}
        return {}


def estimate_island_realtime_telemetry(
    config: Dict[str, Any],
    weather: Dict[str, Any],
    air_quality: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Calcula la estimación física en tiempo real (MW) por isla cruzando:
    - Curva de potencia eólica a 80m de altura (cut-in: 11 km/h, nominal: 43 km/h)
    - Irradiancia solar real atenuada por el polvo sahariano (PM10 / Dust)
    - Capacidad instalada oficial de cada isla en Red Eléctrica
    """
    wind_80m = weather.get("wind_speed_80m_kmh") or 0.0
    ghi = weather.get("solar_ghi_w_m2") or 0.0
    dust = air_quality.get("saharan_dust_ug_m3") or 0.0

    # 1. Factor de capacidad eólico según velocidad del alisio a 80m (buje de turbina)
    if wind_80m < 11.0 or wind_80m > 90.0:
        wind_cf = 0.0
    elif wind_80m >= 45.0:
        wind_cf = 0.85
    else:
        # Curva cúbica suavizada típica de aerogeneradores en Canarias
        wind_cf = min(0.85, ((wind_80m - 11.0) / 34.0) ** 1.6)

    # 2. Factor de capacidad solar fotovoltaico penalizado por calima (ensuciamiento + dispersión)
    calima_penalty = max(0.65, 1.0 - (dust / 1000.0))
    solar_cf = min(0.90, (ghi / 1000.0) * calima_penalty)

    est_wind_mw = round(config["installed_wind_mw"] * wind_cf, 2)
    est_solar_mw = round(config["installed_solar_mw"] * solar_cf, 2)
    
    # Ajuste horario de demanda insular (valle nocturno vs punta diurna)
    hour_utc = datetime.now(timezone.utc).hour
    load_factor = 0.62 if (0 <= hour_utc <= 6) else (0.92 if (18 <= hour_utc <= 22) else 0.82)
    est_demand_mw = round(config["peak_demand_ref_mw"] * load_factor, 2)

    total_renewable_mw = round(min(est_demand_mw, est_wind_mw + est_solar_mw), 2)
    fossil_backup_mw = round(max(0.0, est_demand_mw - total_renewable_mw), 2)
    renewable_share_pct = round((total_renewable_mw / est_demand_mw) * 100, 2) if est_demand_mw > 0 else 0.0

    return {
        "estimated_demand_mw": est_demand_mw,
        "estimated_wind_mw": est_wind_mw,
        "estimated_solar_mw": est_solar_mw,
        "estimated_fossil_backup_mw": fossil_backup_mw,
        "instant_renewable_share_pct": renewable_share_pct,
        "wind_capacity_factor": round(wind_cf, 3),
        "solar_calima_efficiency_factor": round(calima_penalty, 3)
    }


def build_island_snapshot(island_key: str, config: Dict[str, Any]) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc).isoformat()
    
    air_quality = fetch_calima_and_air_quality(config["lat"], config["lon"])
    weather = fetch_solar_and_wind(config["lat"], config["lon"])
    ree_archipelago_mix = fetch_ree_canarias_official()
    realtime_telemetry = estimate_island_realtime_telemetry(config, weather, air_quality)
    
    dust = air_quality.get("saharan_dust_ug_m3") or 0.0
    clouds = weather.get("cloud_cover_pct") or 0
    calima_solar_impact_index = round((dust * (100 - clouds) / 100.0), 2)

    return {
        "island_id": island_key,
        "timestamp": now_utc,
        "island_name": config["name"],
        "coordinates": {"lat": config["lat"], "lon": config["lon"]},
        "calima_metrics": air_quality,
        "weather_renewables": weather,
        "derived_features": {
            "calima_solar_attenuation_index": calima_solar_impact_index
        },
        "island_realtime_estimation_mw": realtime_telemetry,
        "ree_canarias_consolidated_mix": ree_archipelago_mix
    }


def lambda_handler(event: Optional[Dict] = None, context: Optional[Any] = None) -> Dict[str, Any]:
    logger.info("Iniciando ingesta energética y de calima en Canarias...")
    results = []
    
    for island_key, config in ISLANDS_CONFIG.items():
        snapshot = build_island_snapshot(island_key, config)
        results.append(snapshot)
        
    return {
        "statusCode": 200,
        "ingested_islands": len(results),
        "data": results
    }


if __name__ == "__main__":
    payload = lambda_handler()
    print(json.dumps(payload, indent=2, ensure_ascii=False))