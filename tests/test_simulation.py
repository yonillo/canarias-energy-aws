import json
import os
import sys
import unittest
from decimal import Decimal

# Añadir 'src' al path para importar el módulo de la Lambda
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from lambda_function import (
    ISLANDS_CONFIG,
    estimate_island_realtime_telemetry,
    fetch_calima_and_air_quality,
    fetch_solar_and_wind,
)


class TestCanariasEnergySimulation(unittest.TestCase):
    def setUp(self):
        self.sample_config = {
            "name": "Gran Canaria",
            "lat": 27.8500,
            "lon": -15.4300,
            "ree_geo_id": 8749,
            "installed_wind_mw": 300.0,
            "installed_solar_mw": 100.0,
            "peak_demand_ref_mw": 500.0,
        }

    def test_wind_capacity_factor_cutin_and_cutout(self):
        """Comprueba los límites de corte (cut-in <11 km/h y cut-out >90 km/h) de los aerogeneradores."""
        # Caso 1: Viento insuficiente (< 11 km/h)
        weather_calm = {"wind_speed_80m_kmh": 8.0, "solar_ghi_w_m2": 0.0}
        air_quality = {"saharan_dust_ug_m3": 0.0}
        res_calm = estimate_island_realtime_telemetry(self.sample_config, weather_calm, air_quality)
        self.assertEqual(res_calm["wind_capacity_factor"], 0.0)
        self.assertEqual(res_calm["estimated_wind_mw"], 0.0)

        # Caso 2: Viento extremo (> 90 km/h, desconexión por seguridad de turbinas)
        weather_storm = {"wind_speed_80m_kmh": 95.0, "solar_ghi_w_m2": 0.0}
        res_storm = estimate_island_realtime_telemetry(self.sample_config, weather_storm, air_quality)
        self.assertEqual(res_storm["wind_capacity_factor"], 0.0)
        self.assertEqual(res_storm["estimated_wind_mw"], 0.0)

        # Caso 3: Régimen nominal (>= 45 km/h)
        weather_nominal = {"wind_speed_80m_kmh": 48.0, "solar_ghi_w_m2": 0.0}
        res_nom = estimate_island_realtime_telemetry(self.sample_config, weather_nominal, air_quality)
        self.assertEqual(res_nom["wind_capacity_factor"], 0.85)
        self.assertEqual(res_nom["estimated_wind_mw"], 255.0)

    def test_solar_calima_attenuation(self):
        """Verifica la penalización fotovoltaica modelada según la concentración de polvo sahariano."""
        weather_sunny = {"wind_speed_80m_kmh": 20.0, "solar_ghi_w_m2": 800.0}

        # Atmósfera limpia (sin polvo)
        res_clean = estimate_island_realtime_telemetry(
            self.sample_config, weather_sunny, {"saharan_dust_ug_m3": 0.0}
        )
        self.assertEqual(res_clean["solar_calima_efficiency_factor"], 1.0)

        # Episodio de calima moderada (200 ug/m3 de polvo sahariano)
        res_calima = estimate_island_realtime_telemetry(
            self.sample_config, weather_sunny, {"saharan_dust_ug_m3": 200.0}
        )
        self.assertEqual(res_calima["solar_calima_efficiency_factor"], 0.8)
        self.assertLess(res_calima["estimated_solar_mw"], res_clean["estimated_solar_mw"])

        # Episodio de calima extrema (> 1000 ug/m3): no debe bajar de 0.65 de suelo mínimo
        res_extreme = estimate_island_realtime_telemetry(
            self.sample_config, weather_sunny, {"saharan_dust_ug_m3": 2500.0}
        )
        self.assertEqual(res_extreme["solar_calima_efficiency_factor"], 0.65)

    def test_energy_balance_and_fossil_backup(self):
        """Verifica que la demanda estimada sea cubierta por renovables + respaldo fósil sin valores negativos."""
        weather = {"wind_speed_80m_kmh": 30.0, "solar_ghi_w_m2": 500.0}
        air_quality = {"saharan_dust_ug_m3": 50.0}
        res = estimate_island_realtime_telemetry(self.sample_config, weather, air_quality)

        demand = res["estimated_demand_mw"]
        wind = res["estimated_wind_mw"]
        solar = res["estimated_solar_mw"]
        fossil = res["estimated_fossil_backup_mw"]

        self.assertGreater(demand, 0.0)
        self.assertGreaterEqual(fossil, 0.0)
        self.assertAlmostEqual(demand, min(demand, wind + solar) + fossil, delta=0.1)
        self.assertGreaterEqual(res["instant_renewable_share_pct"], 0.0)
        self.assertLessEqual(res["instant_renewable_share_pct"], 100.0)

    def test_islands_configuration_integrity(self):
        """Verifica que todas las 6 islas del archipiélago tengan datos válidos de potencia y coordenadas."""
        expected_islands = [
            "gran_canaria",
            "tenerife",
            "lanzarote_fuerteventura",
            "la_palma",
            "la_gomera",
            "el_hierro",
        ]
        self.assertEqual(set(ISLANDS_CONFIG.keys()), set(expected_islands))

        for key, conf in ISLANDS_CONFIG.items():
            self.assertIn("lat", conf)
            self.assertIn("lon", conf)
            self.assertGreater(conf["installed_wind_mw"], 0)
            self.assertGreater(conf["peak_demand_ref_mw"], 0)
            # Rango geográfico de Canarias (27-29.5 N, -18 a -13 W)
            self.assertTrue(27.0 <= conf["lat"] <= 29.5, f"Latitud fuera de rango en {key}")
            self.assertTrue(-19.0 <= conf["lon"] <= -13.0, f"Longitud fuera de rango en {key}")

    def test_dynamodb_decimal_serializability(self):
        """Comprueba que los datos numéricos con float se conviertan limpiamente a Decimal para DynamoDB."""
        sample_item = {
            "island_id": "gran_canaria",
            "solar_cf": 0.456,
            "nested": {"dust_ug": 18.5},
        }
        item_decimal = json.loads(json.dumps(sample_item), parse_float=Decimal)
        self.assertIsInstance(item_decimal["solar_cf"], Decimal)
        self.assertIsInstance(item_decimal["nested"]["dust_ug"], Decimal)
        self.assertEqual(str(item_decimal["solar_cf"]), "0.456")


if __name__ == "__main__":
    unittest.main()
