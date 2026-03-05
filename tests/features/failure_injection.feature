Feature: New failure type injection
  As a simulation engineer
  I want FailureInjector to correctly inject oil pressure drops, vibration anomalies,
  and brake degradation into vehicle telemetry
  So that the ML model can learn to detect these new failure patterns

  Background:
    Given a failure injector for an AMBULANCE vehicle

  Scenario: Oil pressure drop is injected into telemetry
    Given an OIL_PRESSURE_DROP failure is activated
    When the injector is applied to fresh telemetry after 60 seconds
    Then the telemetry oil_pressure_bar should be less than 3.3

  Scenario: Oil pressure does not drop below zero
    Given an OIL_PRESSURE_DROP failure is activated
    When the injector is applied to fresh telemetry after 700 seconds
    Then the telemetry oil_pressure_bar should be greater than or equal to 0.0

  Scenario: Vibration anomaly is injected into telemetry
    Given a VIBRATION_ANOMALY failure is activated
    When the injector is applied to fresh telemetry after 120 seconds
    Then the telemetry vibration_ms2 should be greater than 1.5

  Scenario: Vibration is capped at 50 m/s²
    Given a VIBRATION_ANOMALY failure is activated
    When the injector is applied to fresh telemetry after 6000 seconds
    Then the telemetry vibration_ms2 should be less than or equal to 50.0

  Scenario: Brake degradation is injected into telemetry
    Given a BRAKE_DEGRADATION failure is activated
    When the injector is applied to fresh telemetry after 120 seconds
    Then the telemetry brake_pad_mm should be less than 11.7

  Scenario: Brake pad thickness does not go below zero
    Given a BRAKE_DEGRADATION failure is activated
    When the injector is applied to fresh telemetry after 5000 seconds
    Then the telemetry brake_pad_mm should be greater than or equal to 0.0

  Scenario: Normal telemetry is unchanged when no failure is active
    Given no failure is activated
    When the injector is applied to fresh telemetry after 0 seconds
    Then the telemetry engine_temp_celsius should be approximately 88.0 within 10.0 degrees
