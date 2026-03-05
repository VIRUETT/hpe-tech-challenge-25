Feature: Severity-scaled emergency unit dispatch
  As a city dispatcher
  I want unit counts to scale with emergency severity
  So that critical incidents receive more resources than low-priority ones

  Background:
    Given a baseline of 2 ambulances, 1 fire trucks, and 1 police units

  Scenario: LOW severity halves the unit count (minimum 1)
    When the units are scaled by LOW severity
    Then the result should have 1 ambulance
    And the result should have 1 fire_truck
    And the result should have 1 police

  Scenario: MODERATE severity keeps the baseline count
    When the units are scaled by MODERATE severity
    Then the result should have 2 ambulances
    And the result should have 1 fire_truck
    And the result should have 1 police

  Scenario: HIGH severity adds 50% more units
    When the units are scaled by HIGH severity
    Then the result should have 3 ambulances
    And the result should have 2 fire_trucks
    And the result should have 2 police

  Scenario: SEVERE severity doubles the unit count
    When the units are scaled by SEVERE severity
    Then the result should have 4 ambulances
    And the result should have 2 fire_trucks
    And the result should have 2 police

  Scenario: CRITICAL severity triples the unit count
    When the units are scaled by CRITICAL severity
    Then the result should have 6 ambulances
    And the result should have 3 fire_trucks
    And the result should have 3 police

  Scenario: Zero count vehicle types remain zero regardless of severity
    Given a baseline of 0 ambulances, 0 fire trucks, and 2 police units
    When the units are scaled by CRITICAL severity
    Then the result should have 0 ambulances
    And the result should have 0 fire_trucks
    And the result should have 6 police
