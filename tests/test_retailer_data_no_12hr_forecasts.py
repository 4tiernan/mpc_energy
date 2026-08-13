from mpc_energy.External_Interfaces.amber_api import price_data


def test_price_data_has_no_legacy_12hr_forecast_fields():
    assert "general_12hr_forecast" not in price_data.__dataclass_fields__
    assert "feedIn_12hr_forecast" not in price_data.__dataclass_fields__
    assert "general_12hr_forecast_sorted" not in price_data.__dataclass_fields__
    assert "feedIn_12hr_forecast_sorted" not in price_data.__dataclass_fields__
