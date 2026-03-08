Feature: Emergency lifecycle timing
  As a dispatcher
  I want emergencies to follow simulation-time lifecycle rules
  So that unit availability is recovered predictably

  Background:
    Given a fast-forward emergency service with one ambulance

  Scenario: Emergency enters in-progress when first unit arrives
    Given a new medical emergency that needs 1 ambulance
    When the emergency is dispatched
    And the first assigned unit arrives on scene
    Then the emergency status should be in_progress

  Scenario: In-progress emergency reaches planned auto-resolution window
    Given a new medical emergency that needs 1 ambulance
    When the emergency is dispatched
    And the first assigned unit arrives on scene
    And simulation time advances to the planned resolution window
    Then the emergency should be eligible for auto-resolution

  Scenario: Dispatched emergency is dismissed after stall timeout
    Given a new medical emergency that needs 1 ambulance
    When the emergency is dispatched
    And simulation time advances by 25 minutes
    Then the emergency should be eligible for auto-dismissal
