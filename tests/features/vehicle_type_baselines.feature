Feature: Per-vehicle-type sensor baselines
  As a simulation engineer
  I want each vehicle type to generate telemetry with type-specific baselines
  So that ambulances, fire trucks, and police vehicles reflect real-world differences

  Scenario: Ambulance engine temperature is near the ambulance baseline
    Given a telemetry generator for an AMBULANCE vehicle
    When 50 telemetry ticks are generated
    Then the mean engine_temp_celsius should be approximately 88.0 within 5.0 degrees

  Scenario: Fire truck engine temperature is near the fire truck baseline
    Given a telemetry generator for a FIRE_TRUCK vehicle
    When 50 telemetry ticks are generated
    Then the mean engine_temp_celsius should be approximately 95.0 within 5.0 degrees

  Scenario: Police engine temperature is near the police baseline
    Given a telemetry generator for a POLICE vehicle
    When 50 telemetry ticks are generated
    Then the mean engine_temp_celsius should be approximately 85.0 within 5.0 degrees

  Scenario: Ambulance and fire truck baseline temperatures are distinct
    Given a telemetry generator for an AMBULANCE vehicle
    And a second telemetry generator for a FIRE_TRUCK vehicle
    When 50 telemetry ticks are generated for each
    Then the mean engine temperatures should differ by at least 4.0 degrees

  Scenario: Ambulance battery voltage is near the ambulance baseline
    Given a telemetry generator for an AMBULANCE vehicle
    When 50 telemetry ticks are generated
    Then the mean battery_voltage should be approximately 13.8 within 1.0 volts

  Scenario: Fire truck battery voltage is near the fire truck baseline
    Given a telemetry generator for a FIRE_TRUCK vehicle
    When 50 telemetry ticks are generated
    Then the mean battery_voltage should be approximately 13.6 within 1.0 volts

  Scenario: Police battery voltage is near the police baseline
    Given a telemetry generator for a POLICE vehicle
    When 50 telemetry ticks are generated
    Then the mean battery_voltage should be approximately 14.2 within 1.0 volts
