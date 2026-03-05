import os
import time

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


def fetch_fleet():
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/fleet", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def fetch_emergencies():
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/emergencies", timeout=5)
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
        return "#FF0000", "🚨"
    if status == "idle":
        return "#16a34a", "🚑"
    if status == "en_route":
        return "#2563eb", "🚒"
    if status == "on_scene":
        return "#7c3aed", "🚓"
    return "#6b7280", "🚗"


def _render_folium_map(fleet_data: dict | None, emergencies: list | None) -> None:
    """Build and render a Folium OpenStreetMap with vehicles and emergencies.

    Vehicles are shown as coloured circle markers with popup details.
    Emergencies are shown as orange markers. The SF boundary box is drawn
    as a semi-transparent rectangle so operators can see the constrained zone.

    Args:
        fleet_data: JSON payload from GET /fleet, or None if unavailable.
        emergencies: JSON list from GET /emergencies, or None if unavailable.
    """
    sf_center = [(SF_LAT_MIN + SF_LAT_MAX) / 2, (SF_LON_MIN + SF_LON_MAX) / 2]
    fmap = folium.Map(
        location=sf_center,
        zoom_start=13,
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

            popup_html = (
                f"<b>{icon_emoji} {v['vehicle_id']}</b><br>"
                f"Type: {v.get('vehicle_type', 'N/A').replace('_', ' ').title()}<br>"
                f"Status: <span style='color:{color}'><b>{status.replace('_', ' ').upper()}</b></span><br>"
                f"Speed: {v.get('speed_kmh', 0):.0f} km/h<br>"
                f"Battery: {v.get('battery_voltage', 0):.1f} V<br>"
                f"Fuel: {v.get('fuel_level_percent', 0):.0f} %<br>"
                f"Alert: {'YES' if has_alert else 'No'}"
            )

            folium.CircleMarker(
                location=[loc["latitude"], loc["longitude"]],
                radius=9,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.85,
                weight=2,
                popup=folium.Popup(popup_html, max_width=220),
                tooltip=f"{icon_emoji} {v['vehicle_id']} ({status})",
            ).add_to(fmap)

    # --- Emergency markers ---
    if emergencies:
        for e in emergencies:
            if e.get("status") == "resolved":
                continue

            has_any_marker = True
            severity = e.get("severity", "unknown")
            etype = e.get("emergency_type", "unknown").replace("_", " ").title()

            popup_html = (
                f"<b>🚨 {etype}</b><br>"
                f"Severity: <b>{severity.upper()}</b><br>"
                f"Status: {e.get('status', 'N/A')}<br>"
                f"Description: {e.get('description', '')}<br>"
                f"Assigned: {', '.join(e.get('assigned_vehicles', [])) or 'None'}"
            )

            folium.Marker(
                location=[e["latitude"], e["longitude"]],
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"🚨 {etype} ({severity})",
                icon=folium.Icon(color="orange", icon="exclamation-sign", prefix="glyphicon"),
            ).add_to(fmap)

    if not has_any_marker:
        # Fallback label when orchestrator is offline
        folium.Marker(
            location=sf_center,
            tooltip="Waiting for data…",
            icon=folium.Icon(color="gray", icon="time", prefix="glyphicon"),
        ).add_to(fmap)

    components.html(fmap._repr_html_(), height=520)


def main():
    st.title("🚑 Project AEGIS - City Operations Dashboard")
    st.markdown(
        "Real-time visualization of emergency vehicles, orchestrator actions, and city scenarios."
    )

    # Top level metrics
    fleet_data = fetch_fleet()
    emergencies = fetch_emergencies()

    if fleet_data:
        summary = fleet_data.get("summary", {})
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Vehicles", summary.get("total_vehicles", 0))
        col2.metric("Available", summary.get("available_vehicles", 0))
        col3.metric("On Mission", summary.get("on_mission", 0))
        col4.metric("Active Alerts", summary.get("vehicles_with_alerts", 0))
    else:
        st.warning(
            f"Could not connect to Orchestrator API at {ORCHESTRATOR_URL}. Make sure it is running."
        )

    st.markdown("---")

    col_map, col_list = st.columns([2, 1])

    with col_map:
        st.subheader("City Map (Live)")
        _render_folium_map(fleet_data, emergencies)

    with col_list:
        st.subheader("🚨 Active Scenarios & Crimes")
        if emergencies:
            active_emergencies = [e for e in emergencies if e.get("status") != "resolved"]
            if active_emergencies:
                for e in active_emergencies:
                    with st.expander(
                        f"{e['emergency_type'].upper()} - {e['status']}", expanded=True
                    ):
                        st.write(f"**Severity:** {e['severity']}")
                        st.write(f"**Description:** {e['description']}")
                        st.write(
                            f"**Assigned Vehicles:** {', '.join(e.get('assigned_vehicles', [])) or 'None'}"
                        )
            else:
                st.success("No active emergencies in the city.")
        else:
            st.info("No emergency data available.")

        st.subheader("⏱️ Emergency Timeline")
        if emergencies:
            # Sort by created_at descending to show latest first
            sorted_em = sorted(emergencies, key=lambda x: x.get("created_at", ""), reverse=True)
            for e in sorted_em[:10]:  # show last 10
                created = str(e.get("created_at", ""))[:19].replace("T", " ")
                status = e.get("status", "unknown")
                icon = "✅" if status == "resolved" else ("🚨" if status == "pending" else "🚙")

                st.markdown(f"**{created}** {icon} {e['emergency_type'].upper()} ({status})")
                if e.get("dispatched_at") and status != "resolved":
                    st.text(f"    → Dispatched {len(e.get('assigned_vehicles', []))} units")
        else:
            st.info("No timeline events yet.")

    st.markdown("---")
    st.subheader("🚓 Agents (Vehicles)")
    if fleet_data and "vehicles" in fleet_data:
        df_vehicles = pd.DataFrame(fleet_data["vehicles"])
        if not df_vehicles.empty:
            display_cols = [
                "vehicle_id",
                "vehicle_type",
                "operational_status",
                "is_available",
                "battery_voltage",
                "fuel_level_percent",
                "has_active_alert",
            ]

            def highlight_alerts(row):
                if row.get("has_active_alert"):
                    return ["background-color: rgba(255, 0, 0, 0.2)"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_vehicles[display_cols].style.apply(highlight_alerts, axis=1),
                use_container_width=True,
            )
        else:
            st.info("No vehicles active.")

    # Auto-refresh
    time.sleep(2)
    st.rerun()


if __name__ == "__main__":
    main()
