import os
import time
from datetime import datetime

import folium
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from src.vehicle_agent.config import (
    SF_LAT_MAX,
    SF_LAT_MIN,
    SF_LON_MAX,
    SF_LON_MIN,
)

# Configure page
st.set_page_config(
    page_title="Project AEGIS - Real-Time Dashboard",
    page_icon="🚑",
    layout="wide",
)

# API config
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

# Severity colours used in multiple places
_SEVERITY_COLOR = {
    "critical": "#dc2626",
    "warning": "#d97706",
    "info": "#2563eb",
}
_SEVERITY_BADGE = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "🔵",
}


def fetch_fleet() -> dict | None:
    """Fetch full fleet state from the orchestrator API.

    Returns:
        Parsed JSON dict or None on failure.
    """
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/fleet", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_emergencies() -> list | None:
    """Fetch all emergencies from the orchestrator API.

    Returns:
        Parsed JSON list or None on failure.
    """
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/emergencies", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_alerts() -> list | None:
    """Fetch active predictive maintenance alerts from the orchestrator API.

    Returns:
        Parsed JSON list or None on failure.
    """
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/alerts", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_crime_predictions() -> list | None:
    """Fetch active city crime predictions from the orchestrator API."""
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/crime-predictions", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _vehicle_icon(status: str, has_alert: bool) -> tuple[str, str]:
    """Return (color, emoji) for a vehicle marker based on its status.

    Args:
        status: Operational status string from the API.
        has_alert: Whether the vehicle has an active maintenance alert.

    Returns:
        Tuple of (hex color string, emoji character).
    """
    if has_alert:
        return "#dc2626", "🚨"
    if status == "idle":
        return "#16a34a", "🚑"
    if status == "en_route":
        return "#2563eb", "🚒"
    if status == "on_scene":
        return "#7c3aed", "🚓"
    return "#6b7280", "🚗"


def _render_folium_map(
    fleet_data: dict | None,
    emergencies: list | None,
    predictions: list | None,
    *,
    center: list[float] | None = None,
    zoom: int = 13,
) -> None:
    """Build and render a Folium OpenStreetMap with vehicles and emergencies.

    Vehicles are shown as coloured circle markers with popup details.
    Emergencies are shown as orange markers. The SF boundary box is drawn
    as a semi-transparent rectangle so operators can see the constrained zone.

    Args:
        fleet_data: JSON payload from GET /fleet, or None if unavailable.
        emergencies: JSON list from GET /emergencies, or None if unavailable.
        predictions: JSON list from GET /crime-predictions, or None if unavailable.
        center: Map center [lat, lon]. Defaults to SF center if None.
        zoom: Initial zoom level.
    """
    default_center = [(SF_LAT_MIN + SF_LAT_MAX) / 2, (SF_LON_MIN + SF_LON_MAX) / 2]
    location = center if center is not None else default_center
    fmap = folium.Map(
        location=location,
        zoom_start=zoom,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # Draw the SF operating boundary as a thin dashed rectangle
    folium.Rectangle(
        bounds=[[SF_LAT_MIN, SF_LON_MIN], [SF_LAT_MAX, SF_LON_MAX]],
        color="#6b7280",
        weight=2,
        dash_array="6 4",
        fill=True,
        fill_color="#6b7280",
        fill_opacity=0.04,
        tooltip="SF Operating Boundary",
    ).add_to(fmap)

    has_any_marker = False

    # --- Vehicle markers ---
    if fleet_data and "vehicles" in fleet_data:
        for v in fleet_data["vehicles"]:
            loc = v.get("location")
            if not loc:
                continue

            has_any_marker = True
            status = v.get("operational_status", "unknown")
            has_alert = bool(v.get("has_active_alert"))
            color, icon_emoji = _vehicle_icon(status, has_alert)

            oil = v.get("oil_pressure_bar")
            vib = v.get("vibration_ms2")
            brk = v.get("brake_pad_mm")
            eng = v.get("engine_temp_celsius")

            popup_html = (
                f"<b>{icon_emoji} {v['vehicle_id']}</b><br>"
                f"Type: {v.get('vehicle_type', 'N/A').replace('_', ' ').title()}<br>"
                f"Status: <span style='color:{color}'><b>{status.replace('_', ' ').upper()}</b></span><br>"
                f"<hr style='margin:4px 0'>"
                f"Engine: {eng:.1f} °C<br>"
                if eng is not None
                else "Engine: N/A<br>"
            )
            popup_html = (
                f"<b>{icon_emoji} {v['vehicle_id']}</b><br>"
                f"Type: {v.get('vehicle_type', 'N/A').replace('_', ' ').title()}<br>"
                f"Status: <span style='color:{color}'><b>{status.replace('_', ' ').upper()}</b></span><br>"
                f"<hr style='margin:4px 0'>"
                f"Engine: {f'{eng:.1f} °C' if eng is not None else 'N/A'}<br>"
                f"Battery: {v.get('battery_voltage', 0):.1f} V<br>"
                f"Fuel: {v.get('fuel_level_percent', 0):.0f} %<br>"
                f"Oil: {f'{oil:.2f} bar' if oil is not None else 'N/A'}<br>"
                f"Vibration: {f'{vib:.2f} m/s²' if vib is not None else 'N/A'}<br>"
                f"Brake pad: {f'{brk:.1f} mm' if brk is not None else 'N/A'}<br>"
                f"<b>Alert: {'YES' if has_alert else 'No'}</b>"
            )

            folium.CircleMarker(
                location=[loc["latitude"], loc["longitude"]],
                radius=9,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.85,
                weight=2,
                popup=folium.Popup(popup_html, max_width=240),
                tooltip=f"{icon_emoji} {v['vehicle_id']} ({status})",
            ).add_to(fmap)

    # --- Emergency markers ---
    if emergencies:
        for e in emergencies:
            if e.get("status") in {"resolved", "cancelled", "dismissed"}:
                continue

            has_any_marker = True
            severity = e.get("severity", "unknown")
            etype = e.get("emergency_type", "unknown").replace("_", " ").title()
            description = e.get("description", "")

            # Customize marker style by emergency source/type
            if "ACTUAL CRIME" in description:
                marker_color = "red"
                marker_icon = "fire"
                tooltip_icon = "🔥 CRIME"
            else:
                marker_color = "orange"
                marker_icon = "exclamation-sign"
                tooltip_icon = "🚨"

            popup_html = (
                f"<b>{tooltip_icon} {etype}</b><br>"
                f"Severity: <b>{severity}</b><br>"
                f"Status: {e.get('status', 'N/A')}<br>"
                f"Description: {description}<br>"
                f"Assigned: {', '.join(e.get('assigned_vehicles', [])) or 'None'}"
            )

            folium.Marker(
                location=[e["latitude"], e["longitude"]],
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"{tooltip_icon} {etype} (sev {severity})",
                icon=folium.Icon(color=marker_color, icon=marker_icon, prefix="glyphicon"),
            ).add_to(fmap)

    # --- Prediction markers ---
    if predictions:
        for prediction in predictions:
            lat = prediction.get("latitude")
            lon = prediction.get("longitude")
            if lat is None or lon is None:
                continue

            has_any_marker = True
            neighborhood = prediction.get("neighborhood", "Unknown area")
            crime_type = (
                str(prediction.get("predicted_crime_type", "unknown")).replace("_", " ").title()
            )
            probability = float(prediction.get("risk_probability", 0.0))
            severity = prediction.get("severity", "warning")

            marker_color = "darkpurple" if severity == "critical" else "blue"
            tooltip_icon = "👁️ AI"
            popup_html = (
                f"<b>{tooltip_icon} Prediction</b><br>"
                f"Neighborhood: <b>{neighborhood}</b><br>"
                f"Crime Type: <b>{crime_type}</b><br>"
                f"Risk: <b>{probability:.0%}</b><br>"
                f"Severity: <b>{severity}</b><br>"
                f"Description: {prediction.get('description', 'N/A')}"
            )

            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{tooltip_icon} {neighborhood} ({probability:.0%})",
                icon=folium.Icon(color=marker_color, icon="eye-open", prefix="glyphicon"),
            ).add_to(fmap)

    if not has_any_marker:
        # Fallback label when orchestrator is offline
        folium.Marker(
            location=default_center,
            tooltip="Waiting for data…",
            icon=folium.Icon(color="gray", icon="time", prefix="glyphicon"),
        ).add_to(fmap)

    components.html(fmap._repr_html_(), height=520)


def _render_alert_panel(alerts: list | None) -> None:
    """Render the active ML predictive alerts panel.

    Args:
        alerts: List of alert dicts from GET /alerts, or None.
    """
    st.subheader("ML Predictive Alerts")
    if not alerts:
        st.success("No active predictive alerts.")
        return

    # Sort: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_alerts = sorted(alerts, key=lambda a: severity_order.get(a.get("severity", "info"), 3))

    for alert in sorted_alerts:
        sev = alert.get("severity", "info")
        badge = _SEVERITY_BADGE.get(sev, "⚪")
        color = _SEVERITY_COLOR.get(sev, "#6b7280")  # noqa: F841
        vid = alert.get("vehicle_id", "?")
        component = alert.get("component", "?")
        prob = alert.get("failure_probability", 0.0)
        conf = alert.get("confidence", 0.0)
        likely_h = alert.get("predicted_failure_likely_hours", 0.0)
        action = alert.get("recommended_action", "")
        factors = alert.get("contributing_factors", [])
        telem = alert.get("related_telemetry", {})

        with st.expander(
            f"{badge} {vid} — {component.replace('_', ' ').upper()} ({sev.upper()})",
            expanded=(sev == "critical"),
        ):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Failure Prob", f"{prob:.0%}")
            col_b.metric("Confidence", f"{conf:.0%}")
            col_c.metric("ETA to Failure", f"~{likely_h:.1f} h")

            st.markdown(f"**Action:** {action}")
            if factors:
                st.markdown("**Contributing factors:** " + ", ".join(factors))

            if telem:
                telem_cols = st.columns(len(telem))
                for col, (k, v) in zip(telem_cols, telem.items(), strict=False):
                    if isinstance(v, float):
                        col.metric(k.replace("_", " ").title(), f"{v:.2f}")
                    else:
                        col.metric(k.replace("_", " ").title(), str(v))


def _render_prediction_panel(predictions: list | None) -> None:
    """Render active AI crime predictions below predictive maintenance alerts."""
    st.subheader("AI Crime Predictions")
    if not predictions:
        st.info("No active AI crime predictions.")
        return

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_predictions = sorted(
        predictions,
        key=lambda item: severity_order.get(item.get("severity", "info"), 3),
    )

    for prediction in sorted_predictions:
        sev = prediction.get("severity", "info")
        badge = _SEVERITY_BADGE.get(sev, "⚪")
        neighborhood = prediction.get("neighborhood", "Unknown neighborhood")
        probability = float(prediction.get("risk_probability", 0.0))
        crime_type = (
            str(prediction.get("predicted_crime_type", "unknown")).replace("_", " ").title()
        )

        with st.expander(
            f"{badge} {neighborhood} — {crime_type} ({probability:.0%})",
            expanded=(sev == "critical"),
        ):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Risk Probability", f"{probability:.0%}")
            col_b.metric("Confidence", f"{float(prediction.get('confidence', 0.0)):.0%}")
            col_c.metric("Severity", sev.upper())

            st.write(f"**Description:** {prediction.get('description', 'N/A')}")
            st.write(f"**Source:** {prediction.get('source', 'ai_crime_predictor')}")
            st.write(f"**Location:** {prediction.get('latitude')}, {prediction.get('longitude')}")


def main() -> None:
    """Main Streamlit application entrypoint."""
    st.title("Project AEGIS - City Operations Dashboard")
    st.markdown(
        "Real-time visualization of emergency vehicles, orchestrator actions, and city scenarios."
    )

    # Persist map view so reruns do not reset zoom/center
    default_center = [(SF_LAT_MIN + SF_LAT_MAX) / 2, (SF_LON_MIN + SF_LON_MAX) / 2]
    if "map_center" not in st.session_state:
        st.session_state.map_center = default_center
    if "map_zoom" not in st.session_state:
        st.session_state.map_zoom = 13

    # Fetch all data
    fleet_data = fetch_fleet()
    emergencies = fetch_emergencies()
    alerts = fetch_alerts()
    predictions = fetch_crime_predictions()

    # -----------------------------------------------------------------------
    # Top-level metrics row
    # -----------------------------------------------------------------------
    if fleet_data:
        summary = fleet_data.get("summary", {})
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Vehicles", summary.get("total_vehicles", 0))
        col2.metric("Available", summary.get("available_vehicles", 0))
        col3.metric("On Mission", summary.get("on_mission", 0))
        col4.metric("Active Alerts", summary.get("vehicles_with_alerts", 0))
        col5.metric("Active Emergencies", summary.get("active_emergencies", 0))
    else:
        st.warning(
            f"Could not connect to Orchestrator API at {ORCHESTRATOR_URL}. Make sure it is running."
        )

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Map + Emergencies panel
    # -----------------------------------------------------------------------
    col_map, col_list = st.columns([2, 1])

    with col_map:
        st.subheader("City Map (Live)")
        sim_time_str = "Waiting for orchestrator..."

        if fleet_data and "summary" in fleet_data:
            raw_time = fleet_data["summary"].get("simulated_time")
            if raw_time:
                try:
                    # Format it beautifully, e.g., "Friday 18:30"
                    dt = datetime.fromisoformat(raw_time)
                    sim_time_str = dt.strftime("%A, %B %d - %H:%M")
                except ValueError:
                    pass

        # Display it using a markdown badge
        st.markdown(f"**🕒 Simulated Clock:** `{sim_time_str}`")
        _render_folium_map(
            fleet_data,
            emergencies,
            predictions,
            center=st.session_state.map_center,
            zoom=st.session_state.map_zoom,
        )

    with col_list:
        st.subheader("Active Scenarios & Crimes")
        if emergencies:
            inactive_statuses = {"resolved", "cancelled", "dismissed"}
            active_emergencies = [
                e for e in emergencies if e.get("status") not in inactive_statuses
            ]
            if active_emergencies:
                for e in active_emergencies:
                    with st.expander(
                        f"{e['emergency_type'].upper()} — sev {e['severity']} ({e['status']})",
                        expanded=True,
                    ):
                        st.write(f"**Description:** {e['description']}")
                        units = e.get("units_required", {})
                        if units:
                            parts = []
                            if units.get("ambulances"):
                                parts.append(f"{units['ambulances']} amb")
                            if units.get("fire_trucks"):
                                parts.append(f"{units['fire_trucks']} fire")
                            if units.get("police"):
                                parts.append(f"{units['police']} police")
                            st.write(f"**Units required:** {', '.join(parts) or 'N/A'}")
                        assigned = e.get("assigned_vehicles", [])
                        st.write(f"**Assigned:** {', '.join(assigned) or 'None'}")
            else:
                st.success("No active emergencies in the city.")
        else:
            st.info("No emergency data available.")

        st.subheader("Emergency Timeline")
        if emergencies:
            sorted_em = sorted(emergencies, key=lambda x: x.get("created_at", ""), reverse=True)
            for e in sorted_em[:10]:
                created = str(e.get("created_at", ""))[:19].replace("T", " ")
                status = e.get("status", "unknown")
                icon_map = {
                    "resolved": "✅",
                    "dismissed": "📴",
                    "cancelled": "⛔",
                    "pending": "🚨",
                }
                icon = icon_map.get(status, "🚙")
                st.markdown(f"**{created}** {icon} {e['emergency_type'].upper()} ({status})")
                if status == "dismissed" and e.get("dismissed_at"):
                    dismissed_at = str(e.get("dismissed_at", ""))[:19].replace("T", " ")
                    st.text(f"    → dismissed at {dismissed_at}")
                if e.get("dispatched_at") and status not in {"resolved", "dismissed", "cancelled"}:
                    st.text(f"    → {len(e.get('assigned_vehicles', []))} units dispatched")
        else:
            st.info("No timeline events yet.")

    st.markdown("---")

    # -----------------------------------------------------------------------
    # ML Predictive Alerts
    # -----------------------------------------------------------------------
    _render_alert_panel(alerts)
    _render_prediction_panel(predictions)

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Vehicle fleet table — all sensor columns
    # -----------------------------------------------------------------------
    st.subheader("Agents (Vehicles) — Live Telemetry")
    if fleet_data and "vehicles" in fleet_data:
        df_vehicles = pd.DataFrame(fleet_data["vehicles"])
        if not df_vehicles.empty:
            # Ensure all sensor columns exist (may be absent before first tick)
            for col in [
                "engine_temp_celsius",
                "oil_pressure_bar",
                "vibration_ms2",
                "brake_pad_mm",
            ]:
                if col not in df_vehicles.columns:
                    df_vehicles[col] = None

            display_cols = [
                "vehicle_id",
                "vehicle_type",
                "operational_status",
                "is_available",
                "engine_temp_celsius",
                "battery_voltage",
                "fuel_level_percent",
                "oil_pressure_bar",
                "vibration_ms2",
                "brake_pad_mm",
                "has_active_alert",
            ]

            # Round floats for display
            float_cols = [
                "engine_temp_celsius",
                "battery_voltage",
                "fuel_level_percent",
                "oil_pressure_bar",
                "vibration_ms2",
                "brake_pad_mm",
            ]
            for fc in float_cols:
                if fc in df_vehicles.columns:
                    df_vehicles[fc] = df_vehicles[fc].apply(
                        lambda x: round(x, 2) if x is not None and pd.notna(x) else x
                    )

            def highlight_alerts(row: pd.Series) -> list[str]:
                if row.get("has_active_alert"):
                    return ["background-color: rgba(220, 38, 38, 0.15)"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_vehicles[display_cols].style.apply(highlight_alerts, axis=1),
                use_container_width=True,
            )

            # Per-type breakdown
            if "summary" in (fleet_data or {}):
                by_type = fleet_data["summary"].get("by_type", {})
                if by_type:
                    st.caption("Fleet breakdown by type")
                    type_cols = st.columns(len(by_type))
                    for tc, (vtype, counts) in zip(type_cols, by_type.items(), strict=False):
                        tc.metric(
                            vtype.replace("_", " ").title(),
                            f"{counts['available']}/{counts['total']} avail",
                        )
        else:
            st.info("No vehicles active.")

    # Auto-refresh every 2 seconds
    time.sleep(2)
    st.rerun()


if __name__ == "__main__":
    main()
