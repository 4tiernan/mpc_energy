import datetime
import json
import threading
from typing import Any, Dict, List
import os

import numpy as np
import paho.mqtt.client as mqtt
from dash import Dash, Input, Output, State, dcc, html
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config_manager
import const


CONTROL_MODE_ORDER = [
    "Grid Import",
    "Self Consumption",
    "Solar To Load",
    "Export Excess Solar",
    "Export All Solar",
    "Dispatch",
    "Unable to determine",
]

CONTROL_MODE_COLORS = {
    "Grid Import": "#fa6be0",
    "Self Consumption": "#a6ebfc",
    "Solar To Load": "#D6FFA4",
    "Export Excess Solar": "#7efd1d",
    "Export All Solar": "#02d938",
    "Dispatch": "#fbe94a",
    "Unable to determine": "#ff0000",
}


class RealtimeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: Dict[str, Any] = {}
        self._version = 0

    def set_payload(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._payload = payload
            self._version += 1

    def get(self) -> tuple[Dict[str, Any], int]:
        with self._lock:
            return dict(self._payload), self._version


STATE = RealtimeState()


def round_to_nearest_5min(dt: datetime.datetime) -> datetime.datetime:
    seconds = dt.minute * 60 + dt.second
    rounded_seconds = int((seconds + 150) // 300 * 300)
    return dt.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(seconds=rounded_seconds)


def parse_time_index(output: Dict[str, Any]) -> List[Any]:
    try:
        return [
            round_to_nearest_5min(datetime.datetime.fromisoformat(t.replace("Z", "+00:00")))
            for t in output["time_index"]
        ]
    except Exception:
        return list(range(len(output.get("battery_power", []))))


def round_list(data: List[float], dp: int = 2) -> List[float]:
    return [round(d, dp) for d in data]


def build_figure(output: Dict[str, Any]) -> go.Figure:
    time_index = parse_time_index(output)
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.25, 0.25],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": True}]],
    )

    mode_to_int = {mode: i for i, mode in enumerate(CONTROL_MODE_ORDER)}
    mode_numeric = [mode_to_int.get(m, mode_to_int["Unable to determine"]) for m in output.get("plan_modes", [])]

    shapes = []
    historical_data_len = output.get("historical_data_length", 0)
    if len(time_index) > max(historical_data_len + 1, 0):
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=time_index[0],
                x1=time_index[historical_data_len + 1],
                y0=0,
                y1=1,
                fillcolor="grey",
                opacity=0.6,
                layer="below",
                line_width=0,
            )
        )

    for t, mode in enumerate(output.get("plan_modes", [])):
        if t >= len(time_index):
            break
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=time_index[t],
                x1=time_index[t] + datetime.timedelta(minutes=5) if hasattr(time_index[t], "year") else t + 1,
                y0=0,
                y1=1,
                fillcolor=CONTROL_MODE_COLORS.get(mode, "#bdbdbd"),
                opacity=0.4,
                layer="below",
                line_width=0,
            )
        )

    fig.update_layout(shapes=shapes)

    fig.add_trace(
        go.Scatter(x=time_index, y=mode_numeric, mode="lines", line=dict(shape="hv", width=3), name="Control Mode"),
        row=3,
        col=1,
        secondary_y=False,
    )

    grid_power = np.array(output.get("grid_net", []), dtype=float)
    grid_energy_kwh = np.round(grid_power * (5 / 60), 2) if grid_power.size else np.array([])
    fig.add_trace(
        go.Bar(
            x=time_index,
            y=grid_energy_kwh,
            name="Grid Energy (kWh)",
            marker_color=["green" if e < 0 else "red" for e in grid_energy_kwh],
            opacity=0.6,
        ),
        row=3,
        col=1,
        secondary_y=True,
    )

    fig.update_yaxes(
        tickmode="array",
        tickvals=list(mode_to_int.values()),
        ticktext=list(mode_to_int.keys()),
        row=3,
        col=1,
        title="Control Mode",
    )

    if grid_energy_kwh.size:
        max_abs = float(max(abs(grid_energy_kwh.min()), abs(grid_energy_kwh.max())) * 1.2) or 1.0
        fig.update_yaxes(
            range=[-max_abs, max_abs],
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor="black",
            row=3,
            col=1,
            secondary_y=True,
        )

    fig.add_trace(
        go.Scatter(x=time_index, y=round_list(output.get("battery_power", [])), name="Battery Power (kW)", line=dict(color="blue", shape="hv")),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=time_index, y=round_list(output.get("load_power", [])), name="Load", line=dict(color="orange", shape="hv")),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=time_index, y=round_list(output.get("solar_forecast", [])), name="Available Solar", line=dict(color="limegreen", dash="dash", shape="hv")),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=time_index, y=round_list(output.get("solar_used", [])), name="Solar Used", line=dict(color="limegreen", shape="hv")),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=time_index, y=round_list(output.get("inverter_power", [])), name="Inverter Power", line=dict(color="purple", shape="hv")),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=time_index, y=round_list(output.get("grid_net", [])), name="Grid Net (+buy / -sell)", line=dict(color="black", dash="dot", shape="hv")),
        row=1,
        col=1,
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(x=time_index, y=[round(v * 100) for v in output.get("prices_buy", [])], name="Buy Price (c/kWh)", line=dict(color="green", shape="hv")),
        row=1,
        col=1,
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(x=time_index, y=[round(v * 100) for v in output.get("prices_sell", [])], name="Sell Price (c/kWh)", line=dict(color="red", shape="hv")),
        row=1,
        col=1,
        secondary_y=True,
    )

    soc = output.get("soc", [])
    fig.add_trace(go.Scatter(x=time_index, y=round_list(soc[:-1] if soc else []), name="SOC (kWh)", line=dict(color="purple")), row=2, col=1)

    soc_min = output.get("soc_min")
    soc_max = output.get("soc_max")
    if soc_min is not None:
        fig.add_hline(y=soc_min, row=2, col=1, line_dash="dash", line_color="red")
    if soc_max is not None:
        fig.add_hline(y=soc_max, row=2, col=1, line_dash="dash", line_color="red")

    fig.update_yaxes(title_text="Power (kW)", autorange=True, row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Price (c/kWh)", autorange=True, row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="SOC (kWh)", autorange=True, row=2, col=1)
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,0.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0,0,0,0.15)")

    fig.update_layout(
        template="plotly_white",
        height=1000,
        title="Battery Schedule & SOC (MPC) - Dash",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=70, b=20),
    )
    return fig


def build_metrics(payload: Dict[str, Any]) -> List[html.Div]:
    items = [
        ("Profit Already Today", payload.get("profit_already_today"), "$"),
        ("Profit Remaining Today", payload.get("profit_remaining_today"), "$"),
        ("Profit Tomorrow", payload.get("profit_tomorrow"), "$"),
    ]
    if payload.get("demand_tarrif"):
        items.append(("Peak Demand", payload.get("peak_demand"), "kW"))

    cards = []
    for label, value, unit in items:
        if value is None:
            display = "--"
        elif unit == "$":
            display = f"${float(value):.2f}"
        else:
            display = f"{float(value):.2f} {unit}"
        cards.append(
            html.Div(
                [html.Div(label, className="metric-label"), html.Div(display, className="metric-value")],
                className="metric-card",
            )
        )
    return cards


def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        STATE.set_payload(payload)
    except Exception:
        return


def start_mqtt_listener() -> mqtt.Client:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(config_manager.MQTT_USER, config_manager.MQTT_PASS)
    client.on_message = on_message
    client.connect(const.MQTT_HOST, const.MQTT_PORT)
    client.subscribe("home/mpc/output")
    client.loop_start()
    return client


def create_app() -> Dash:
    ingress_prefix = os.getenv("INGRESS_ENTRY", "/")
    if not ingress_prefix.endswith("/"):
        ingress_prefix = f"{ingress_prefix}/"

    app = Dash(
        __name__,
        requests_pathname_prefix=ingress_prefix,
        routes_pathname_prefix=ingress_prefix,
    )
    app.layout = html.Div(
        [
            html.H2("🔋 MPC Plan Dashboard (Dash)", style={"marginBottom": "8px"}),
            html.Div(id="metrics-row", className="metrics-row"),
            html.Div(id="status", style={"margin": "8px 0", "color": "#555"}),
            dcc.Graph(id="mpc-graph", style={"height": "78vh"}),
            dcc.Interval(id="poller", interval=500, n_intervals=0),
            dcc.Store(id="last-version", data=-1),
        ],
        style={"padding": "12px 18px", "fontFamily": "Arial, sans-serif"},
    )

    app.index_string = """
    <!DOCTYPE html>
    <html>
      <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
          .metrics-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 8px; }
          .metric-card { background: #f7f9fc; border: 1px solid #dde3ed; border-radius: 8px; padding: 10px; }
          .metric-label { color: #5f6775; font-size: 12px; margin-bottom: 4px; }
          .metric-value { color: #111827; font-size: 22px; font-weight: 700; }
        </style>
      </head>
      <body>
        {%app_entry%}
        <footer>
          {%config%}
          {%scripts%}
          {%renderer%}
        </footer>
      </body>
    </html>
    """

    @app.callback(
        Output("mpc-graph", "figure"),
        Output("metrics-row", "children"),
        Output("status", "children"),
        Output("last-version", "data"),
        Input("poller", "n_intervals"),
        State("last-version", "data"),
    )
    def update_dashboard(_: int, last_version: int):
        payload, version = STATE.get()
        if not payload:
            if last_version == -1:
                return (
                    go.Figure(),
                    [],
                    "Waiting for MQTT data from home/mpc/output...",
                    -1,
                )
            raise PreventUpdate

        if version == last_version:
            raise PreventUpdate

        fig = build_figure(payload)
        metrics = build_metrics(payload)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        status = f"Updated from MQTT payload version {version} at {ts}"
        return fig, metrics, status, version

    return app


def main() -> None:
    _mqtt_client = start_mqtt_listener()
    app = create_app()
    app.run(host="0.0.0.0", port=8501, debug=False)


if __name__ == "__main__":
    main()
