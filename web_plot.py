import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
from energy_controller import ControlMode
import numpy as np

CONTROL_MODE_ORDER = [
    ControlMode.GRID_IMPORT.value,
    ControlMode.SELF_CONSUMPTION.value,
    ControlMode.SOLAR_TO_LOAD.value,
    ControlMode.EXPORT_EXCESS_SOLAR.value,
    ControlMode.EXPORT_ALL_SOLAR.value,
    ControlMode.DISPATCH.value,
    "Unable to determine",
]

CONTROL_MODE_COLORS = {
    ControlMode.GRID_IMPORT.value:        "#fa6be0",  # blue
    ControlMode.SELF_CONSUMPTION.value:   "#a6ebfc",  # green
    ControlMode.SOLAR_TO_LOAD.value:      "#D6FFA4",  # darker green
    ControlMode.EXPORT_EXCESS_SOLAR.value:"#7efd1d",  # orange
    ControlMode.EXPORT_ALL_SOLAR.value:   "#02d938",  # dark orange
    ControlMode.DISPATCH.value:            "#fbe94a",  # yellow
    "Unable to determine":                 "#ff0000",  # grey
}


def round_to_nearest_5min(dt: datetime) -> datetime:
    seconds = dt.minute * 60 + dt.second
    rounding = 5 * 60  # 5 minutes in seconds
    rounded_seconds = int((seconds + rounding / 2) // rounding * rounding)

    return dt.replace(
        minute=0,
        second=0,
        microsecond=0
    ) + datetime.timedelta(seconds=rounded_seconds)

# -----------------------------
# Plot: SOC trajectory (functional)
# -----------------------------
def plot_mpc_results(st, output):
    """
    Plot MPC results using Plotly (dual-axis, 2 subplots)
    """

    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    col1.subheader("🔋 MPC Plan Dashboard")

    col2.metric(
        label="Profit Today",
        value=f"${st.session_state.mpc_output['profit_today']:.2f}"
    )

    col3.metric(
        label="Profit Tomorrow",
        value=f"${st.session_state.mpc_output['profit_tomorrow']:.2f}"
    )

    # -------------------------------
    # Extract limits safely
    # -------------------------------
    soc_min = output.get("soc_min", None)
    soc_max = output.get("soc_max", None)

    # -------------------------------
    # Time index handling
    # -------------------------------
    try:
        time_index = [round_to_nearest_5min(datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))) for t in output["time_index"]]
    except Exception:
        time_index = list(range(len(output["battery_power"])))

    # -------------------------------
    # Create figure
    # -------------------------------
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.25, 0.25],  # Row height proportions
        specs=[
            [{'secondary_y': True}],   # Row 1 (power + prices)
            [{'secondary_y': False}],  # Row 2 (SOC)
            [{'secondary_y': True}]   # Row 3 (control mode)
        ]
    )

    mode_to_int = {mode: i for i, mode in enumerate(CONTROL_MODE_ORDER)}
    int_to_mode = {i: mode for mode, i in mode_to_int.items()}

    mode_numeric = [
        mode_to_int.get(m, mode_to_int["Unable to determine"])
        for m in output["plan_modes"]
    ]


    shapes = []

    historical_data_len = output["historical_data_length"] # Get the length of the historical data portion of the data

    # Shade past data
    past_shape = dict(
        type="rect",
        xref="x",
        yref="paper",  # span the full height of the subplot
        x0=time_index[0],   # start of past (beginning of your data)
        x1=time_index[historical_data_len],             # end of past (current time)
        y0=0,
        y1=1,
        fillcolor="grey",
        opacity=0.6,
        layer="below",
        line_width=0,
    )
    shapes.append(past_shape)

    for t, mode in enumerate(output["plan_modes"]):
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",        # span full subplot height
                x0=time_index[t],
                x1=time_index[t] + datetime.timedelta(minutes=5),
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
        go.Scatter(
            x=time_index,
            y=mode_numeric,
            mode="lines",
            line=dict(shape="hv", width=3),
            name="Control Mode",
        ),
        row=3,
        col=1,
        secondary_y=False
    )

    
    DT_HOURS = 5 / 60
    grid_power = np.array(output["grid_net"])
    grid_energy_kwh = np.round(grid_power * DT_HOURS, 2)
    fig.add_trace(
        go.Bar(
            x=time_index,
            y=grid_energy_kwh,
            name="Grid Energy (kWh)",
            marker_color=[
                "green" if e < 0 else "red"
                for e in grid_energy_kwh
            ],
            opacity=0.6
        ),
        row=3,
        col=1,
        secondary_y=True
    )
    fig.update_yaxes(
        title_text="Grid Energy (kWh / 5 min)",
        row=3,
        col=1
    )

    fig.update_yaxes(
        tickmode="array",
        tickvals=list(mode_to_int.values()),
        ticktext=list(mode_to_int.keys()),
        row=3,
        col=1,
        title="Control Mode",
    )

    max_abs = max(abs(grid_energy_kwh.min()), abs(grid_energy_kwh.max()))*1.2
    fig.update_yaxes(
        range=[-max_abs, max_abs],
        zeroline=True,
        zerolinewidth=2,
        zerolinecolor="black",
        row=3,
        col=1,
        secondary_y=True
    )

    fig.update_yaxes(
        title_text="Grid Energy (kWh / 5 min)",
        zeroline=True,
        zerolinewidth=2,
        zerolinecolor="black",
        row=3,
        col=1,
        secondary_y=True
    )

    # ===============================
    # TOP: POWER + PRICE
    # ===============================

    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["battery_power"]),
        name="Battery Power (kW)",
        line=dict(color="blue", shape="hv")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["load_power"]),
        name="Load",
        line=dict(color="orange", shape="hv")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["solar_forecast"]),
        name="Available Solar",
        line=dict(color="limegreen", dash="dash", shape="hv")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["solar_used"]),
        name="Solar Used",
        line=dict(color="limegreen", shape="hv")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["inverter_power"]),
        name="Inverter Power",
        line=dict(color="purple", shape="hv")
    ), row=1, col=1, secondary_y=False)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["grid_net"]),
        name="Grid Net (+buy / -sell)",
        line=dict(color="black", dash="dot", shape="hv")
    ), row=1, col=1, secondary_y=False)

    # Prices (right axis)
    fig.add_trace(go.Scatter(
        x=time_index,
        y=[round(v*100) for v in output["prices_buy"]],
        name="Buy Price (c/kWh)",
        line=dict(color="green", shape="hv")
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=[round(v*100) for v in output["prices_sell"]],
        name="Sell Price (c/kWh)",
        line=dict(color="red", shape="hv")
    ), row=1, col=1, secondary_y=True)

    fig.add_hline(y=0, row=1, col=1, line_color="black", line_width=1)

    # ===============================
    # BOTTOM: SOC
    # ===============================
    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["soc"][:-1]),
        name="SOC (kWh)",
        line=dict(color="purple")
    ), row=2, col=1)

    # SOC constraint lines (only if present)
    if soc_min is not None:
        fig.add_hline(y=soc_min, row=2, col=1, line_dash="dash", line_color="red")

    if soc_max is not None:
        fig.add_hline(y=soc_max, row=2, col=1, line_dash="dash", line_color="red")


    # ===============================
    # AXES LIMITS (soft defaults)
    # ===============================
    fig.update_yaxes(
        title_text="Power (kW)",
        range=[-15, 15],
        autorange=True,
        row=1, col=1, secondary_y=False
    )

    fig.update_yaxes(
        title_text="Price (c/kWh)",
        autorange=True,
        row=1, col=1, secondary_y=True
    )

    fig.update_yaxes(
        title_text="SOC (kWh)",
        range=[0, 40],
        autorange=True,
        row=2, col=1
    )

    # ===============================
    # GRID (major + minor, pale)
    # ===============================
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(0,0,0,0.15)",
        minor=dict(
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)"
        )
    )

    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(0,0,0,0.15)",
        minor=dict(
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)"
        )
    )

    # ===============================
    # LAYOUT
    # ===============================
    fig.update_layout(
        template="plotly_white",
        height=1000,
        title="Battery Schedule & SOC (MPC)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )


    st.plotly_chart(fig, width='stretch')

def round_list(data, dp=2):
    return [round(d,dp) for d in data]