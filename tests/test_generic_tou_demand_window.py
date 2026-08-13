from datetime import datetime, timezone

from mpc_energy.External_Interfaces.generic_tou import GenericTOUInterface


class DummyHA:
    local_tz = timezone.utc


def test_generic_tou_builds_demand_window_for_time_range():
    generic = GenericTOUInterface(
        ha=DummyHA(),
        import_windows_json='[{"start": "00:00", "end": "23:59", "price": 30}]',
        export_windows_json='[{"start": "00:00", "end": "23:59", "price": 5}]',
        demand_tarrif_price="10",
        demand_tarrif_window_start="16:00",
        demand_tarrif_window_end="21:00",
    )

    timeline_start = datetime(2024, 1, 1, 15, 55, tzinfo=timezone.utc)
    forecast = generic._build_demand_window_5min(intervals_5m=12, timeline_start=timeline_start)

    assert generic.demand_tarrif is True
    assert forecast[0] is False
    assert forecast[1] is False
    assert forecast[2] is False
    assert forecast[3] is True
    assert forecast[4] is True
    assert forecast[5] is True
    assert forecast[6] is True
    assert forecast[7] is True
    assert forecast[8] is True
    assert forecast[9] is True
    assert forecast[10] is True
    assert forecast[11] is False
