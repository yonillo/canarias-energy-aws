-- =============================================================================
-- CANARIAS ENERGY & CALIMA MONITOR - ATHENA DDL & ANALYTICAL QUERIES
-- =============================================================================
-- Este script define la base de datos y la tabla externa particionada (Hive style)
-- sobre el Data Lake en Amazon S3, además de consultas analíticas clave.
-- =============================================================================

-- 1. CREACIÓN DE BASE DE DATOS EN AWS GLUE DATA CATALOG
CREATE DATABASE IF NOT EXISTS canarias_energy_lake
COMMENT 'Data Lake analítico de telemetría de energía y calima en Canarias';

-- 2. CREACIÓN DE TABLA EXTERNA PARTICIONADA (NDJSON / Hive Partitioning)
CREATE EXTERNAL TABLE IF NOT EXISTS canarias_energy_lake.island_telemetry (
  island_id STRING COMMENT 'Identificador canónico de la isla',
  `timestamp` STRING COMMENT 'Timestamp ISO8601 UTC de la medición',
  island_name STRING COMMENT 'Nombre legible del sistema insular',
  coordinates STRUCT<
    lat: DOUBLE,
    lon: DOUBLE
  > COMMENT 'Geolocalización del centroide de medición',
  calima_metrics STRUCT<
    pm10_ug_m3: DOUBLE,
    pm2_5_ug_m3: DOUBLE,
    saharan_dust_ug_m3: DOUBLE,
    aerosol_optical_depth: DOUBLE,
    european_aqi: INT,
    calima_status: STRING
  > COMMENT 'Métricas de calidad del aire y polvo sahariano',
  weather_renewables STRUCT<
    temp_c: DOUBLE,
    cloud_cover_pct: INT,
    wind_speed_10m_kmh: DOUBLE,
    wind_speed_80m_kmh: DOUBLE,
    wind_dir_deg: INT,
    solar_ghi_w_m2: DOUBLE,
    solar_direct_w_m2: DOUBLE,
    solar_diffuse_w_m2: DOUBLE,
    solar_diffuse_ratio: DOUBLE
  > COMMENT 'Variables atmosféricas e irradiancia solar',
  derived_features STRUCT<
    calima_solar_attenuation_index: DOUBLE
  > COMMENT 'Índices derivados de impacto meteorológico',
  island_realtime_estimation_mw STRUCT<
    estimated_demand_mw: DOUBLE,
    estimated_wind_mw: DOUBLE,
    estimated_solar_mw: DOUBLE,
    estimated_fossil_backup_mw: DOUBLE,
    instant_renewable_share_pct: DOUBLE,
    wind_capacity_factor: DOUBLE,
    solar_calima_efficiency_factor: DOUBLE
  > COMMENT 'Telemetría física calculada y penetración renovable'
)
PARTITIONED BY (
  year STRING,
  month STRING,
  day STRING
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
WITH SERDEPROPERTIES (
  'ignore.malformed.json' = 'true'
)
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION 's3://<TU_BUCKET_S3_DATA_LAKE>/raw/'
TBLPROPERTIES (
  'classification' = 'json',
  'compressionType' = 'none'
);

-- 3. CARGA DE PARTICIONES HIVE
MSCK REPAIR TABLE canarias_energy_lake.island_telemetry;


-- =============================================================================
-- CONSULTAS ANALÍTICAS DESTACADAS PARA PORTFOLIO / CV
-- =============================================================================

-- Query 1: Impacto directo del Polvo Sahariano en la Eficiencia Solar por Isla
-- Cuantifica la degradación del factor de eficiencia fotovoltaica durante episodios de calima.
SELECT
  island_name,
  calima_metrics.calima_status AS nivel_calima,
  COUNT(*) AS total_muestras_15m,
  ROUND(AVG(calima_metrics.saharan_dust_ug_m3), 2) AS media_polvo_sahariano_ug_m3,
  ROUND(AVG(weather_renewables.solar_ghi_w_m2), 2) AS irradiancia_solar_ghi_media,
  ROUND(AVG(island_realtime_estimation_mw.solar_calima_efficiency_factor), 3) AS factor_eficiencia_solar_medio,
  ROUND(AVG(island_realtime_estimation_mw.estimated_solar_mw), 2) AS generacion_solar_media_mw
FROM canarias_energy_lake.island_telemetry
WHERE weather_renewables.solar_ghi_w_m2 > 100 -- Filtro de horas con luz diurna
GROUP BY island_name, calima_metrics.calima_status
ORDER BY island_name, media_polvo_sahariano_ug_m3 DESC;


-- Query 2: Ranking de Penetración Renovable y Necesidad de Respaldo Fósil
-- Compara el comportamiento de los sistemas eléctricos insulares y el hueco térmico.
SELECT
  island_name,
  year,
  month,
  ROUND(AVG(island_realtime_estimation_mw.instant_renewable_share_pct), 2) AS penetracion_renovable_media_pct,
  ROUND(MAX(island_realtime_estimation_mw.instant_renewable_share_pct), 2) AS penetracion_renovable_pico_pct,
  ROUND(AVG(island_realtime_estimation_mw.estimated_wind_mw), 2) AS eolica_media_mw,
  ROUND(AVG(island_realtime_estimation_mw.estimated_solar_mw), 2) AS solar_media_mw,
  ROUND(AVG(island_realtime_estimation_mw.estimated_fossil_backup_mw), 2) AS respaldo_fosil_medio_mw,
  ROUND(AVG(island_realtime_estimation_mw.estimated_demand_mw), 2) AS demanda_media_mw
FROM canarias_energy_lake.island_telemetry
GROUP BY island_name, year, month
ORDER BY penetracion_renovable_media_pct DESC;


-- Query 3: Rendimiento de los Vientos Alisios a 80m y Factor de Planta Eólico
-- Correlaciona la velocidad a la altura del buje de turbina con la potencia vertida a la red.
SELECT
  island_name,
  CASE
    WHEN weather_renewables.wind_speed_80m_kmh < 11 THEN '1. Debajo de Cut-in (<11 km/h)'
    WHEN weather_renewables.wind_speed_80m_kmh BETWEEN 11 AND 25 THEN '2. Brisa Alisia Ligera (11-25 km/h)'
    WHEN weather_renewables.wind_speed_80m_kmh BETWEEN 25 AND 45 THEN '3. Alisio Óptimo (25-45 km/h)'
    WHEN weather_renewables.wind_speed_80m_kmh BETWEEN 45 AND 90 THEN '4. Régimen Nominal (45-90 km/h)'
    ELSE '5. Corte por Seguridad (>90 km/h)'
  END AS rango_velocidad_80m,
  COUNT(*) AS total_intervalos,
  ROUND(AVG(weather_renewables.wind_speed_80m_kmh), 2) AS velocidad_media_80m_kmh,
  ROUND(AVG(island_realtime_estimation_mw.wind_capacity_factor), 3) AS factor_capacidad_eolico_medio,
  ROUND(AVG(island_realtime_estimation_mw.estimated_wind_mw), 2) AS vertido_eolico_medio_mw
FROM canarias_energy_lake.island_telemetry
GROUP BY 1, 2
ORDER BY island_name, rango_velocidad_80m;
