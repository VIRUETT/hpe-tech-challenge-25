Feature: Vehicle geographic boundary enforcement
  As a city operations dispatcher
  I want IDLE vehicles to stay within San Francisco city limits
  So that the digital twin accurately reflects real-world constraints
  and vehicles do not drift into the ocean or across state lines

  Background:
    Given the San Francisco bounding box is configured

  Scenario: IDLE vehicle starting inside the boundary stays inside after many ticks
    Given an IDLE vehicle positioned at latitude 37.7749 and longitude -122.4194
    When the vehicle generates 500 telemetry ticks
    Then the vehicle latitude should always be between 37.708 and 37.833
    And the vehicle longitude should always be between -122.527 and -122.349

  Scenario: IDLE vehicle placed beyond the southern boundary is clamped and reflected
    Given an IDLE vehicle positioned at latitude 37.700 and longitude -122.4194
    When the vehicle generates 1 telemetry tick
    Then the vehicle latitude should be greater than or equal to 37.708
    And the vehicle heading should point northward

  Scenario: IDLE vehicle placed beyond the northern boundary is clamped and reflected
    Given an IDLE vehicle positioned at latitude 37.840 and longitude -122.4194
    When the vehicle generates 1 telemetry tick
    Then the vehicle latitude should be less than or equal to 37.833
    And the vehicle heading should point southward

  Scenario: IDLE vehicle placed beyond the western boundary is clamped and reflected
    Given an IDLE vehicle positioned at latitude 37.7749 and longitude -122.530
    When the vehicle generates 1 telemetry tick
    Then the vehicle longitude should be greater than or equal to -122.527
    And the vehicle heading should point eastward

  Scenario: IDLE vehicle placed beyond the eastern boundary is clamped and reflected
    Given an IDLE vehicle positioned at latitude 37.7749 and longitude -122.340
    When the vehicle generates 1 telemetry tick
    Then the vehicle longitude should be less than or equal to -122.349
    And the vehicle heading should point westward

  Scenario: EN_ROUTE vehicle dispatched to an emergency within SF is not boundary-clamped
    Given an EN_ROUTE vehicle positioned at latitude 37.7749 and longitude -122.4194
    And the vehicle has a dispatch target at latitude 37.780 and longitude -122.410
    When the vehicle generates 10 telemetry ticks
    Then the vehicle latitude should always be between 37.708 and 37.833
    And the vehicle longitude should always be between -122.527 and -122.349

  Scenario: EN_ROUTE vehicle moving toward target outside boundary stays within SF
    Given an EN_ROUTE vehicle positioned at latitude 37.7749 and longitude -122.4194
    And the vehicle has a dispatch target at latitude 37.72 and longitude -122.52
    When the vehicle generates 150 telemetry ticks
    Then the vehicle latitude should always be between 37.708 and 37.833
    And the vehicle longitude should always be between -122.527 and -122.349

  Scenario: Stopped vehicle position is unchanged regardless of boundary
    Given a vehicle with status ON_SCENE positioned at latitude 37.7749 and longitude -122.4194
    When the vehicle generates 5 telemetry ticks
    Then the vehicle latitude should equal 37.7749
    And the vehicle longitude should equal -122.4194
