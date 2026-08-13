import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime
from typing import Any, Sequence
from plants.base_plant import BasePlant
import numpy as np

CONTROL_MODE_ORDER = [
    BasePlant.ControlMode.GRID_IMPORT,
    BasePlant.ControlMode.PARTIAL_GRID_IMPORT,
    BasePlant.ControlMode.SELF_CONSUMPTION,
    BasePlant.ControlMode.SOLAR_TO_LOAD,
    BasePlant.ControlMode.EXPORT_EXCESS_SOLAR,
    BasePlant.ControlMode.EXPORT_ALL_SOLAR,
    BasePlant.ControlMode.DISPATCH,
    "Unable to determine",
]

CONTROL_MODE_COLORS = {
    BasePlant.ControlMode.GRID_IMPORT:        "#fa6be0",  # pink
    BasePlant.ControlMode.PARTIAL_GRID_IMPORT: "#ffb7ed", # lighter pink
    BasePlant.ControlMode.SELF_CONSUMPTION:   "#a6ebfc",  # blue
    BasePlant.ControlMode.SOLAR_TO_LOAD:      "#D6FFA4",  # lighter green
    BasePlant.ControlMode.EXPORT_EXCESS_SOLAR: "#7efd1d",  # green
    BasePlant.ControlMode.EXPORT_ALL_SOLAR:   "#02d938",  # dark green
    BasePlant.ControlMode.DISPATCH:            "#fbe94a",  # yellow
    "Unable to determine":                 "#ff0000",  # red
}

def contiguous_segments(values) -> list[tuple[int, int, Any]]:
    """Yield contiguous (start_idx, end_idx_exclusive, value) segments for a sequence."""
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

def get_segment_end_time(
    time_index: Sequence[datetime.datetime],
    end_idx_exclusive: int,
    default_step_minutes: int = 5,
) -> datetime.datetime:
    """Return the x-axis endpoint for a segment end index."""
    if end_idx_exclusive < len(time_index):
        return time_index[end_idx_exclusive]

    return time_index[-1] + datetime.timedelta(minutes=default_step_minutes)

def get_segment_midpoint(start_x: Any, end_x: Any) -> Any:
    """Return the midpoint between two x-axis values, preserving datetime semantics."""
    if isinstance(start_x, datetime.datetime) and isinstance(end_x, datetime.datetime):
        return start_x + (end_x - start_x) / 2
    return (start_x + end_x) / 2

def get_segment_width(start_x: Any, end_x: Any) -> float:
    """Calculate a Plotly-compatible segment width for bar or rect visuals."""
    if isinstance(start_x, datetime.datetime) and isinstance(end_x, datetime.datetime):
        return (end_x - start_x).total_seconds() * 1000
    return end_x - start_x



def round_to_nearest_5min(dt: datetime.datetime) -> datetime.datetime:
    """Round a datetime down to the nearest 5-minute slot."""
    seconds = dt.minute * 60 + dt.second
    rounding = 5 * 60  # 5 minutes in seconds
    rounded_seconds = int((seconds + rounding / 2) // rounding * rounding)

    return dt.replace(
        minute=0,
        second=0,
        microsecond=0
    ) + datetime.timedelta(seconds=rounded_seconds)


def calculate_segment_energy_and_profit(
    plan_modes: Sequence[Any],
    grid_net: Sequence[float],
    prices_buy: Sequence[float],
    prices_sell: Sequence[float],
    dt_minutes: int = 5,
) -> list[dict[str, float | int]]:
    """Return the energy and profit for each contiguous control-mode segment."""
    dt_hours = dt_minutes / 60.0
    segments = []
    for start_idx, end_idx_exclusive, _mode in contiguous_segments(plan_modes):
        segment_grid_net = grid_net[start_idx:end_idx_exclusive]
        segment_energy_kwh = np.round(np.array(segment_grid_net, dtype=float) * dt_hours, 2).sum()

        segment_prices_buy = prices_buy[start_idx:end_idx_exclusive]
        segment_prices_sell = prices_sell[start_idx:end_idx_exclusive]
        segment_kwh_import = np.maximum(np.array(segment_grid_net, dtype=float), 0.0) * dt_hours
        segment_kwh_export = np.maximum(-np.array(segment_grid_net, dtype=float), 0.0) * dt_hours
        segment_profit = np.round(
            np.sum(segment_kwh_export * np.array(segment_prices_sell, dtype=float))
            - np.sum(segment_kwh_import * np.array(segment_prices_buy, dtype=float)),
            2,
        )

        segments.append({
            "start_idx": start_idx,
            "end_idx_exclusive": end_idx_exclusive,
            "energy_kwh": float(segment_energy_kwh),
            "profit": float(segment_profit),
        })
    return segments

# -----------------------------
# Plot: SOC trajectory (functional)
# -----------------------------
def plot_mpc_results(st: Any, output: dict[str, Any]) -> None:
    """Render the MPC forecast dashboard, including runtime mode and profit summaries."""

    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    col1.subheader("🔋 MPC Plan Dashboard")

    # Live operating status (no extra HA sensors required; pulled from the existing MPC output payload)
    operating_mode = output.get("operating_mode", "Initialising")
    manual_override = bool(output.get("manual_override", False))
    override_mode = output.get("override_mode")
    override_remaining = output.get("override_remaining_seconds", 0)

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

    col6.write(f"<small><b>Operating Mode</b></small><br><small>{str(operating_mode)}</small>", unsafe_allow_html=True)
    col7.write(f"<small><b>Override Remaining</b></small><br><small>{'Active: ' + str(round(override_remaining/60, 1)) + ' min' if manual_override and override_remaining > 0 else 'Not active'}</small>", unsafe_allow_html=True)

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
    
    # Aggregate grid energy and profit over each contiguous control-mode segment
    segment_x = []
    segment_width = []
    segment_energy_kwh = []
    segment_profit = []
    segment_meta = calculate_segment_energy_and_profit(
        output["plan_modes"],
        output["grid_net"],
        output["prices_buy"],
        output["prices_sell"],
    )

    for segment in segment_meta:
        start_idx = segment["start_idx"]
        end_idx_exclusive = segment["end_idx_exclusive"]
        x0 = time_index[start_idx]
        x1 = get_segment_end_time(time_index, end_idx_exclusive)
        segment_x.append(get_segment_midpoint(x0, x1))
        segment_width.append(get_segment_width(x0, x1))
        segment_energy_kwh.append(segment["energy_kwh"])
        segment_profit.append(segment["profit"])

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
            hovertemplate=(
                "Segment Energy: %{y:.2f} kWh<br>"
                "Segment Profit: $%{customdata[0]:.2f}<extra></extra>"
            ),
            customdata=[[p] for p in segment_profit],
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

    # Add traces for optional loads (power)
    if "optional_loads" in output:
        for load_name, load_data in output["optional_loads"].items():
            if "power" in load_data and load_data["power"] is not None:
                fig.add_trace(go.Scatter(
                    x=time_index,
                    y=round_list(load_data["power"]),
                    name=f"{load_name} Power (kW)",
                    line=dict(width=2, shape="hv") # Color will be assigned by Plotly default
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


    # Add traces for optional loads (SOC)
    if "optional_loads" in output:
        for load_name, load_data in output["optional_loads"].items():
            if "soc_percent" in load_data and load_data["soc_percent"] is not None:
                # SOC arrays have N+1 elements, so slice to N elements for plotting against time_index
                fig.add_trace(go.Scatter(
                    x=time_index,
                    y=round_list(load_data["soc_percent"][:-1]),
                    name=f"{load_name} SOC (%)",
                    line=dict(shape="hv") # Color will be assigned by Plotly default
                ), row=2, col=1, secondary_y=True)

            if "temp_c" in load_data and load_data["temp_c"] is not None:
                # Add temperature trace on secondary Y axis
                fig.add_trace(go.Scatter(
                    x=time_index,
                    y=round_list(load_data["temp_c"][:-1]),
                    name=f"{load_name} Temp (°C)",
                    line=dict(dash="dot", width=2),
                    hovertemplate="%{y:.1f} °C<extra></extra>"
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
        range=[0, 41],
        autorange=False,
        row=2, col=1, secondary_y=False
    )

    fig.update_yaxes(
        title_text="Device SOC (%)",
        range=[0, 101],
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

def round_list(data: Sequence[float], dp: int = 2) -> list[float]:
    """Return a rounded copy of a numeric sequence for plotting and display."""
    return [round(d, dp) for d in data]