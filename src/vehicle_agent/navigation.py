"""Navigation providers for vehicle movement.

Provides a pluggable navigation layer so telemetry generation can use either a
simple geometric movement model or road-constrained routing using OSMnx.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Protocol

import structlog

from src.models.enums import OperationalStatus
from src.vehicle_agent.config import SF_LAT_MAX, SF_LAT_MIN, SF_LON_MAX, SF_LON_MIN

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class NavigationResult:
    """Movement result for one simulation tick."""

    latitude: float
    longitude: float
    heading_degrees: float
    speed_kmh: float
    reached_target: bool = False
    distance_moved_km: float = 0.0


class NavigatorProvider(Protocol):
    """Abstraction for movement and routing providers."""

    def set_target(
        self, current_lat: float, current_lon: float, target_lat: float, target_lon: float
    ) -> None:
        """Set target destination for route following."""

    def clear_target(self) -> None:
        """Clear current target/route."""

    def step(
        self,
        *,
        current_lat: float,
        current_lon: float,
        heading_degrees: float,
        status: OperationalStatus,
        dt_hours: float,
    ) -> NavigationResult:
        """Advance one movement tick."""


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute geodesic distance in kilometers using haversine."""
    r_earth = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r_earth * c


def _bearing_radians(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return initial bearing (radians) from point A to point B."""
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlon = lon2_rad - lon1_rad

    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(
        lat2_rad
    ) * math.cos(dlon)
    return math.atan2(y, x)


def _move_geodesic(
    lat: float, lon: float, bearing: float, distance_km: float
) -> tuple[float, float]:
    """Move from a point along a bearing by a geodesic distance."""
    r_earth = 6371.0
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)

    new_lat = math.asin(
        math.sin(lat1) * math.cos(distance_km / r_earth)
        + math.cos(lat1) * math.sin(distance_km / r_earth) * math.cos(bearing)
    )

    new_lon = lon1 + math.atan2(
        math.sin(bearing) * math.sin(distance_km / r_earth) * math.cos(lat1),
        math.cos(distance_km / r_earth) - math.sin(lat1) * math.sin(new_lat),
    )

    return math.degrees(new_lat), math.degrees(new_lon)


def _apply_sf_boundary(
    lat: float, lon: float, heading_degrees: float
) -> tuple[float, float, float]:
    """Clamp to SF boundary and reflect heading at edges."""
    heading_rad = math.radians(heading_degrees)
    north_component = math.cos(heading_rad)
    east_component = math.sin(heading_rad)
    crossed = False

    if lat < SF_LAT_MIN:
        lat = SF_LAT_MIN
        north_component = abs(north_component)
        crossed = True
    elif lat > SF_LAT_MAX:
        lat = SF_LAT_MAX
        north_component = -abs(north_component)
        crossed = True

    if lon < SF_LON_MIN:
        lon = SF_LON_MIN
        east_component = abs(east_component)
        crossed = True
    elif lon > SF_LON_MAX:
        lon = SF_LON_MAX
        east_component = -abs(east_component)
        crossed = True

    if crossed:
        heading_degrees = math.degrees(math.atan2(east_component, north_component)) % 360

    return lat, lon, heading_degrees


class GeometricNavigator:
    """Default navigator based on geometric movement and target bearing."""

    def __init__(self) -> None:
        self._target_latitude: float | None = None
        self._target_longitude: float | None = None

    def set_target(
        self, current_lat: float, current_lon: float, target_lat: float, target_lon: float
    ) -> None:
        del current_lat, current_lon
        self._target_latitude = target_lat
        self._target_longitude = target_lon

    def clear_target(self) -> None:
        self._target_latitude = None
        self._target_longitude = None

    def step(
        self,
        *,
        current_lat: float,
        current_lon: float,
        heading_degrees: float,
        status: OperationalStatus,
        dt_hours: float,
    ) -> NavigationResult:
        idle_speed = 40.0
        en_route_speed = 80.0

        if status == OperationalStatus.IDLE:
            speed = idle_speed
            heading_degrees += random.uniform(-10.0, 10.0)
            bearing = math.radians(heading_degrees)
        elif (
            status == OperationalStatus.EN_ROUTE
            and self._target_latitude is not None
            and self._target_longitude is not None
        ):
            distance_to_target = _haversine_km(
                current_lat,
                current_lon,
                self._target_latitude,
                self._target_longitude,
            )
            if distance_to_target < 0.05:
                return NavigationResult(
                    latitude=current_lat,
                    longitude=current_lon,
                    heading_degrees=heading_degrees,
                    speed_kmh=0.0,
                    reached_target=True,
                )
            speed = en_route_speed
            bearing = _bearing_radians(
                current_lat, current_lon, self._target_latitude, self._target_longitude
            )
        else:
            return NavigationResult(
                latitude=current_lat,
                longitude=current_lon,
                heading_degrees=heading_degrees,
                speed_kmh=0.0,
            )

        distance_to_move = speed * dt_hours
        new_lat, new_lon = _move_geodesic(current_lat, current_lon, bearing, distance_to_move)
        new_heading = math.degrees(bearing)

        if status in (OperationalStatus.IDLE, OperationalStatus.EN_ROUTE):
            new_lat, new_lon, new_heading = _apply_sf_boundary(new_lat, new_lon, new_heading)

        return NavigationResult(
            latitude=new_lat,
            longitude=new_lon,
            heading_degrees=new_heading,
            speed_kmh=speed,
            distance_moved_km=distance_to_move,
        )


class OSMnxNavigator:
    """Road-constrained navigator for San Francisco using OSMnx + NetworkX.

    Falls back to geometric movement when route planning fails.
    """

    _graph_cache: dict[tuple[str, str], object] = {}

    def __init__(self, *, place_name: str, network_type: str = "drive") -> None:
        self._place_name = place_name
        self._network_type = network_type
        self._fallback = GeometricNavigator()
        self._route_points: list[tuple[float, float]] = []
        self._route_index = 0
        self._target_latitude: float | None = None
        self._target_longitude: float | None = None

    def set_target(
        self, current_lat: float, current_lon: float, target_lat: float, target_lon: float
    ) -> None:
        self._target_latitude = target_lat
        self._target_longitude = target_lon
        self._fallback.set_target(current_lat, current_lon, target_lat, target_lon)
        self._plan_route(current_lat, current_lon, target_lat, target_lon)

    def clear_target(self) -> None:
        self._route_points = []
        self._route_index = 0
        self._target_latitude = None
        self._target_longitude = None
        self._fallback.clear_target()

    def step(
        self,
        *,
        current_lat: float,
        current_lon: float,
        heading_degrees: float,
        status: OperationalStatus,
        dt_hours: float,
    ) -> NavigationResult:
        if status != OperationalStatus.EN_ROUTE:
            return self._fallback.step(
                current_lat=current_lat,
                current_lon=current_lon,
                heading_degrees=heading_degrees,
                status=status,
                dt_hours=dt_hours,
            )

        if not self._route_points:
            return self._fallback.step(
                current_lat=current_lat,
                current_lon=current_lon,
                heading_degrees=heading_degrees,
                status=status,
                dt_hours=dt_hours,
            )

        speed = 80.0
        remaining = speed * dt_hours
        lat = current_lat
        lon = current_lon
        prev_lat = current_lat
        prev_lon = current_lon

        while remaining > 0 and self._route_index < len(self._route_points):
            next_lat, next_lon = self._route_points[self._route_index]
            segment_km = _haversine_km(lat, lon, next_lat, next_lon)
            if segment_km < 1e-6:
                self._route_index += 1
                continue

            prev_lat, prev_lon = lat, lon
            if remaining >= segment_km:
                lat, lon = next_lat, next_lon
                remaining -= segment_km
                self._route_index += 1
            else:
                fraction = remaining / segment_km
                lat = lat + (next_lat - lat) * fraction
                lon = lon + (next_lon - lon) * fraction
                remaining = 0.0

        moved_km = _haversine_km(current_lat, current_lon, lat, lon)
        if moved_km > 1e-6:
            heading = math.degrees(_bearing_radians(prev_lat, prev_lon, lat, lon))
        else:
            heading = heading_degrees

        lat, lon, heading = _apply_sf_boundary(lat, lon, heading)
        reached_target = self._route_index >= len(self._route_points)

        return NavigationResult(
            latitude=lat,
            longitude=lon,
            heading_degrees=heading,
            speed_kmh=0.0 if reached_target else speed,
            reached_target=reached_target,
            distance_moved_km=moved_km,
        )

    def _plan_route(
        self,
        current_lat: float,
        current_lon: float,
        target_lat: float,
        target_lon: float,
    ) -> None:
        graph = self._load_graph()
        if graph is None:
            self._route_points = []
            self._route_index = 0
            return

        try:
            import networkx as nx
            import osmnx as ox

            start_node = ox.distance.nearest_nodes(graph, X=current_lon, Y=current_lat)
            end_node = ox.distance.nearest_nodes(graph, X=target_lon, Y=target_lat)
            node_path = nx.shortest_path(graph, start_node, end_node, weight="length")

            points: list[tuple[float, float]] = []
            for node in node_path:
                node_data = graph.nodes[node]
                points.append((float(node_data["y"]), float(node_data["x"])))

            # Keep original target as final point to avoid stopping at nearest node only.
            points.append((target_lat, target_lon))
            self._route_points = points
            self._route_index = 0
            logger.info(
                "osmnx_route_planned",
                points=len(points),
                place_name=self._place_name,
                network_type=self._network_type,
            )
        except Exception as exc:
            self._route_points = []
            self._route_index = 0
            logger.warning(
                "osmnx_route_planning_failed",
                error=str(exc),
                place_name=self._place_name,
                network_type=self._network_type,
            )

    def _load_graph(self) -> object | None:
        cache_key = (self._place_name, self._network_type)
        if cache_key in self._graph_cache:
            return self._graph_cache[cache_key]

        try:
            import osmnx as ox

            graph = ox.graph_from_place(self._place_name, network_type=self._network_type)
            self._graph_cache[cache_key] = graph
            logger.info(
                "osmnx_graph_loaded",
                place_name=self._place_name,
                network_type=self._network_type,
            )
            return graph
        except Exception as exc:
            logger.warning(
                "osmnx_graph_load_failed",
                error=str(exc),
                place_name=self._place_name,
                network_type=self._network_type,
            )
            return None


def build_navigator(
    provider: str,
    *,
    osmnx_place_name: str,
    osmnx_network_type: str,
) -> NavigatorProvider:
    """Factory for navigation providers."""
    if provider.lower() == "osmnx":
        return OSMnxNavigator(place_name=osmnx_place_name, network_type=osmnx_network_type)
    return GeometricNavigator()
