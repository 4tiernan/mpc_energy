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

def contiguous_segments(values):
    """
    Yield contiguous (start_idx, end_idx_exclusive, value) segments.
    """
    if not values:
        return []

    segments = []
    start = 0
    current = values[0]
    for idx in range(1, len(values)):
        if values[idx] != current:
            segments.append((start, idx, current))
            start = idx
            current = values[idx]
    segments.append((start, len(values), current))
    return segments

def get_segment_end_time(time_index, end_idx_exclusive, default_step_minutes=5):
    """
    Return the x1 value for a segment end index.
    """
    if end_idx_exclusive < len(time_index):
        return time_index[end_idx_exclusive]

    return time_index[-1] + datetime.timedelta(minutes=default_step_minutes)

def get_segment_midpoint(start_x, end_x):
    if isinstance(start_x, datetime.datetime) and isinstance(end_x, datetime.datetime):
        return start_x + (end_x - start_x) / 2
    return (start_x + end_x) / 2

def get_segment_width(start_x, end_x):
    """
    Plotly Bar.width must be numeric.
    For datetime x-axes, width is in milliseconds.
    """
    if isinstance(start_x, datetime.datetime) and isinstance(end_x, datetime.datetime):
        return (end_x - start_x).total_seconds() * 1000
    return end_x - start_x



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

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.subheader("🔋 MPC Plan Dashboard")

    col2.metric(
        label="Profit Already Today",
        value=f"${st.session_state.mpc_output['profit_already_today']:.2f}"
    )

    col3.metric(
        label="Profit Remaining Today",
        value=f"${st.session_state.mpc_output['profit_remaining_today']:.2f}"
    )    

    col4.metric(
        label="Profit Tomorrow",
        value=f"${st.session_state.mpc_output['profit_tomorrow']:.2f}"
    )

    if(output["demand_tarrif"]):
        col5.metric(
            label="Peak Demand (During Demand Window)",
            value=f"{output['peak_demand']:.2f} kW"
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
            [{'secondary_y': True}],  # Row 2 (SOC)
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
    past_end_idx = min(historical_data_len + 1, len(time_index) - 1)
    past_shape = dict(
        type="rect",
        xref="x",
        yref="paper",  # span the full height of the subplot
        x0=time_index[0],   # start of past (beginning of your data)
        x1=time_index[past_end_idx],             # end of past (current time)
        y0=0,
        y1=1,
        fillcolor="grey",
        opacity=0.6,
        layer="below",
        line_width=0,
    )
    shapes.append(past_shape)

    # Merge contiguous control-mode regions to reduce DOM size / render time
    for start_idx, end_idx_exclusive, mode in contiguous_segments(output["plan_modes"]):
        shapes.append(
            dict(
                type="rect",
                xref="x",
                yref="paper",        # span full subplot height
                x0=time_index[start_idx],
                x1=get_segment_end_time(time_index, end_idx_exclusive),
                y0=0,
                y1=1,
                fillcolor=CONTROL_MODE_COLORS.get(mode, "#bdbdbd"),
                opacity=0.4,
                layer="below",
                line_width=0,
            )
        )
    
    # Shade for Demand Window
    if(output["demand_tarrif"]):
        demand_window = output["demand_window_forecast"][:-1]
        for start_idx, end_idx_exclusive, in_window in contiguous_segments(demand_window):
            if in_window:
                shapes.append(dict(
                    type="rect",
                    xref="x",
                    yref="y3",  # SOC subplot y-axis
                    x0=time_index[start_idx],
                    x1=get_segment_end_time(time_index, end_idx_exclusive),
                    y0=0,
                    y1=40,  # or soc_max if available
                    fillcolor="red",
                    opacity=0.3,
                    layer="above",  # draw above other shapes so it's visible
                    line_width=0,
                ))

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
    
    # Aggregate grid energy over each contiguous control-mode segment
    segment_x = []
    segment_width = []
    segment_energy_kwh = []
    for start_idx, end_idx_exclusive, _mode in contiguous_segments(output["plan_modes"]):
        x0 = time_index[start_idx]
        x1 = get_segment_end_time(time_index, end_idx_exclusive)
        segment_x.append(get_segment_midpoint(x0, x1))
        segment_width.append(get_segment_width(x0, x1))
        segment_energy_kwh.append(np.round(grid_energy_kwh[start_idx:end_idx_exclusive].sum(), 2))

    fig.add_trace(
        go.Bar(
            x=segment_x,
            y=segment_energy_kwh,
            width=segment_width,
            name="Grid Energy by Segment (kWh)",
            marker_color=[
                "green" if e < 0 else "red"
                for e in segment_energy_kwh
            ],
            opacity=0.6,
            hovertemplate="Segment Grid Energy: %{y:.2f} kWh<extra></extra>",
        ),
        row=3,
        col=1,
        secondary_y=True
    )
    fig.update_yaxes(
        title_text="Grid Energy (kWh / segment)",
        row=3,
        col=1,
        secondary_y=True
    )

    fig.update_yaxes(
        tickmode="array",
        tickvals=list(mode_to_int.values()),
        ticktext=list(mode_to_int.keys()),
        row=3,
        col=1,
        title="Control Mode",
        secondary_y=False
    )
    

    if segment_energy_kwh:
        max_abs = max(abs(min(segment_energy_kwh)), abs(max(segment_energy_kwh))) * 1.2 # Add 20% padding to max for better visualization
    else:
        max_abs = 1

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
        title_text="Grid Energy (kWh / segment)",
        showticklabels=False,
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

    ev_charging_power = output.get("ev_charging_power")
    if ev_charging_power is None:
        ev_charging_power = [0.0] * len(time_index)
    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(ev_charging_power),
        name="EV Charger (kW)",
        line=dict(color="#8e44ad", width=2, shape="hv")
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

    # Effective Prices (right axis)
    fig.add_trace(go.Scatter(
        x=time_index,
        y=[round(v*100,2) for v in output["effective_prices_buy"]],
        name="Effective Buy Price (c/kWh)",
        line=dict(color="#66bb6a", shape="hv", dash="dash"),  # lighter green + dashed
        visible="legendonly" # Set to "legendonly" to hide by default
    ), row=1, col=1, secondary_y=True)

    fig.add_trace(go.Scatter(
        x=time_index,
        y=[round(v*100,2) for v in output["effective_prices_sell"]],
        name="Effective Sell Price (c/kWh)",
        line=dict(color="#ef5350", shape="hv", dash="dash"),  # lighter red + dashed
        visible="legendonly"
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
    # BOTTOM: EV SOC (if present)
    # ===============================
    
    fig.add_trace(go.Scatter(
        x=time_index,
        y=round_list(output["ev_soc_percent"][:-1]),
        name="EV SOC (%)",
        line=dict(color="blue")
    ), row=2, col=1, secondary_y=True)

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
        autorange=False,
        row=2, col=1, secondary_y=False
    )

    fig.update_yaxes(
        title_text="EV SOC (%)",
        range=[0, 100],
        autorange=False,
        row=2, col=1, secondary_y=True
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