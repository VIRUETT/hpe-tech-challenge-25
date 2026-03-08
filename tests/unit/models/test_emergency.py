"""
Unit tests for emergency models in Project AEGIS.

Tests cover EmergencyType, EmergencyStatus, EmergencySeverity, UnitsRequired,
EMERGENCY_UNITS_DEFAULTS, and Emergency model validation.
"""

from datetime import UTC, datetime

import pytest

from src.models.emergency import (
    EMERGENCY_UNITS_DEFAULTS,
    Emergency,
    EmergencySeverity,
    EmergencyStatus,
    EmergencyType,
    UnitsRequired,
)
from src.models.enums import VehicleType
from src.models.vehicle import Location

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_location() -> Location:
    """Provide a sample Location for emergency tests."""
    return Location(
        latitude=19.4326,
        longitude=-99.1332,
        altitude=2240.0,
        accuracy=10.0,
        heading=0.0,
        speed_kmh=0.0,
        timestamp=datetime(2026, 2, 10, 14, 32, 1, tzinfo=UTC),
    )


@pytest.fixture
def sample_emergency(sample_location: Location) -> Emergency:
    """Provide a sample Emergency for testing."""
    return Emergency(
        emergency_type=EmergencyType.MEDICAL,
        severity=EmergencySeverity.HIGH,
        location=sample_location,
        description="Cardiac arrest, unconscious adult male",
        units_required=UnitsRequired(ambulances=1),
        reported_by="operator_01",
    )


# ---------------------------------------------------------------------------
# EmergencyType enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.models
class TestEmergencyType:
    """Tests for EmergencyType enum."""

    def test_all_types_are_strings(self) -> None:
        """All EmergencyType values should be lowercase strings."""
        for et in EmergencyType:
            assert isinstance(et.value, str)
            assert et.value == et.value.lower()

    def test_expected_types_exist(self) -> None:
        """Verify the full set of expected emergency types."""
        expected = {"medical", "fire", "crime", "accident", "hazmat", "rescue", "natural_disaster"}
        actual = {et.value for et in EmergencyType}
        assert actual == expected

    def test_string_coercion(self) -> None:
        """EmergencyType should be constructable from plain strings."""
        assert EmergencyType("medical") == EmergencyType.MEDICAL
        assert EmergencyType("fire") == EmergencyType.FIRE


# ---------------------------------------------------------------------------
# EmergencyStatus enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.models
class TestEmergencyStatus:
    """Tests for EmergencyStatus enum."""

    def test_all_statuses_are_strings(self) -> None:
        """All EmergencyStatus values should be lowercase strings."""
        for es in EmergencyStatus:
            assert isinstance(es.value, str)

    def test_lifecycle_states_exist(self) -> None:
        """Verify lifecycle states are defined."""
        expected = {
            "pending",
            "dispatching",
            "dispatched",
            "in_progress",
            "resolved",
            "cancelled",
            "dismissed",
        }
        actual = {es.value for es in EmergencyStatus}
        assert actual == expected


# ---------------------------------------------------------------------------
# EmergencySeverity enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.models
class TestEmergencySeverity:
    """Tests for EmergencySeverity enum."""

    def test_values_are_integers_1_to_5(self) -> None:
        """Severity values should be integers from 1 to 5."""
        values = {es.value for es in EmergencySeverity}
        assert values == {1, 2, 3, 4, 5}

    def test_critical_is_highest(self) -> None:
        """CRITICAL should be the highest severity."""
        assert EmergencySeverity.CRITICAL.value == 5

    def test_low_is_lowest(self) -> None:
        """LOW should be the lowest severity."""
        assert EmergencySeverity.LOW.value == 1

    def test_ordering(self) -> None:
        """Severity values should be orderable."""
        assert EmergencySeverity.LOW.value < EmergencySeverity.CRITICAL.value
        assert EmergencySeverity.MODERATE.value < EmergencySeverity.SEVERE.value


# ---------------------------------------------------------------------------
# UnitsRequired model
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.models
class TestUnitsRequired:
    """Tests for UnitsRequired model."""

    def test_default_is_all_zeros(self) -> None:
        """Default UnitsRequired should have all zeros."""
        ur = UnitsRequired()
        assert ur.ambulances == 0
        assert ur.fire_trucks == 0
        assert ur.police == 0

    def test_total_property(self) -> None:
        """total property should sum all unit types."""
        ur = UnitsRequired(ambulances=2, fire_trucks=1, police=1)
        assert ur.total == 4

    def test_total_with_zeros(self) -> None:
        """total should return 0 when all are zero."""
        assert UnitsRequired().total == 0

    def test_units_of_type_ambulance(self) -> None:
        """units_of_type should return correct count for ambulances."""
        ur = UnitsRequired(ambulances=3)
        assert ur.units_of_type(VehicleType.AMBULANCE) == 3

    def test_units_of_type_fire_truck(self) -> None:
        """units_of_type should return correct count for fire trucks."""
        ur = UnitsRequired(fire_trucks=2)
        assert ur.units_of_type(VehicleType.FIRE_TRUCK) == 2

    def test_units_of_type_police(self) -> None:
        """units_of_type should return correct count for police."""
        ur = UnitsRequired(police=4)
        assert ur.units_of_type(VehicleType.POLICE) == 4

    def test_negative_values_rejected(self) -> None:
        """UnitsRequired should reject negative values."""
        with pytest.raises(ValueError):
            UnitsRequired(ambulances=-1)


# ---------------------------------------------------------------------------
# EMERGENCY_UNITS_DEFAULTS
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.models
class TestEmergencyUnitsDefaults:
    """Tests for EMERGENCY_UNITS_DEFAULTS mapping."""

    def test_all_emergency_types_have_defaults(self) -> None:
        """Every EmergencyType should have a default UnitsRequired entry."""
        for et in EmergencyType:
            assert et in EMERGENCY_UNITS_DEFAULTS, f"Missing default for {et}"

    def test_medical_needs_ambulance(self) -> None:
        """Medical emergency should require at least one ambulance."""
        assert EMERGENCY_UNITS_DEFAULTS[EmergencyType.MEDICAL].ambulances >= 1

    def test_fire_needs_fire_truck(self) -> None:
        """Fire emergency should require at least one fire truck."""
        assert EMERGENCY_UNITS_DEFAULTS[EmergencyType.FIRE].fire_trucks >= 1

    def test_crime_needs_police(self) -> None:
        """Crime emergency should require at least one police unit."""
        assert EMERGENCY_UNITS_DEFAULTS[EmergencyType.CRIME].police >= 1

    def test_all_defaults_have_at_least_one_unit(self) -> None:
        """Every default should require at least one unit total."""
        for et, ur in EMERGENCY_UNITS_DEFAULTS.items():
            assert ur.total >= 1, f"Default for {et} requires zero units"


# ---------------------------------------------------------------------------
# Emergency model
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.models
class TestEmergency:
    """Tests for Emergency model creation and validation."""

    def test_emergency_valid_creation(self, sample_emergency: Emergency) -> None:
        """Emergency should be created with valid data."""
        assert sample_emergency.emergency_type == EmergencyType.MEDICAL
        assert sample_emergency.status == EmergencyStatus.PENDING
        assert sample_emergency.severity == EmergencySeverity.HIGH
        assert sample_emergency.description == "Cardiac arrest, unconscious adult male"

    def test_emergency_id_auto_generated(self, sample_emergency: Emergency) -> None:
        """emergency_id should be auto-generated as a UUID string."""
        assert len(sample_emergency.emergency_id) == 36
        assert sample_emergency.emergency_id.count("-") == 4

    def test_emergency_default_status_is_pending(self, sample_location: Location) -> None:
        """Default status for a new emergency should be PENDING."""
        e = Emergency(
            emergency_type=EmergencyType.FIRE,
            location=sample_location,
            description="Building fire",
        )
        assert e.status == EmergencyStatus.PENDING

    def test_emergency_default_severity_is_high(self, sample_location: Location) -> None:
        """Default severity should be HIGH."""
        e = Emergency(
            emergency_type=EmergencyType.ACCIDENT,
            location=sample_location,
            description="Multi-vehicle accident",
        )
        assert e.severity == EmergencySeverity.HIGH

    def test_emergency_created_at_auto_set(self, sample_emergency: Emergency) -> None:
        """created_at should be set automatically."""
        assert sample_emergency.created_at is not None
        assert isinstance(sample_emergency.created_at, datetime)

    def test_emergency_dispatched_at_initially_none(self, sample_emergency: Emergency) -> None:
        """dispatched_at should be None for a new emergency."""
        assert sample_emergency.dispatched_at is None

    def test_emergency_resolved_at_initially_none(self, sample_emergency: Emergency) -> None:
        """resolved_at should be None for a new emergency."""
        assert sample_emergency.resolved_at is None

    def test_emergency_notes_initially_empty(self, sample_emergency: Emergency) -> None:
        """notes should be an empty list for a new emergency."""
        assert sample_emergency.notes == []

    def test_emergency_location_stored(
        self, sample_emergency: Emergency, sample_location: Location
    ) -> None:
        """Location should be stored correctly."""
        assert sample_emergency.location.latitude == sample_location.latitude
        assert sample_emergency.location.longitude == sample_location.longitude

    def test_emergency_description_required(self, sample_location: Location) -> None:
        """description is required and should raise if missing."""
        with pytest.raises(ValueError):
            Emergency(  # type: ignore[call-arg]
                emergency_type=EmergencyType.MEDICAL,
                location=sample_location,
            )

    def test_emergency_serialization(self, sample_emergency: Emergency) -> None:
        """Emergency should serialize to a dict without errors."""
        data = sample_emergency.model_dump()
        assert data["emergency_type"] == "medical"
        assert data["status"] == "pending"
        assert "emergency_id" in data
        assert "location" in data

    def test_emergency_json_roundtrip(self, sample_emergency: Emergency) -> None:
        """Emergency should survive a JSON round-trip."""
        json_str = sample_emergency.model_dump_json()
        restored = Emergency.model_validate_json(json_str)
        assert restored.emergency_id == sample_emergency.emergency_id
        assert restored.emergency_type == sample_emergency.emergency_type
        assert restored.severity == sample_emergency.severity

    def test_two_emergencies_have_different_ids(self, sample_location: Location) -> None:
        """Each Emergency instance should get a unique ID."""
        e1 = Emergency(
            emergency_type=EmergencyType.MEDICAL,
            location=sample_location,
            description="First",
        )
        e2 = Emergency(
            emergency_type=EmergencyType.MEDICAL,
            location=sample_location,
            description="Second",
        )
        assert e1.emergency_id != e2.emergency_id

    def test_emergency_with_optional_address(self, sample_location: Location) -> None:
        """Emergency can include an optional address string."""
        e = Emergency(
            emergency_type=EmergencyType.CRIME,
            location=sample_location,
            description="Armed robbery",
            address="Calle Madero 42, CDMX",
        )
        assert e.address == "Calle Madero 42, CDMX"

    def test_emergency_with_custom_units_required(self, sample_location: Location) -> None:
        """UnitsRequired should be stored and accessible."""
        ur = UnitsRequired(ambulances=2, fire_trucks=1)
        e = Emergency(
            emergency_type=EmergencyType.ACCIDENT,
            location=sample_location,
            description="Multi-car crash with fire",
            units_required=ur,
        )
        assert e.units_required.ambulances == 2
        assert e.units_required.fire_trucks == 1
