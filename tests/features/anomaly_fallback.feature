Feature: Rule-based fallback during ML warm-up
  As a system operator
  I want the vehicle agent to use the rule-based anomaly detector for the first 10 ticks
  So that predictive alerts fire even before the ML sliding window is full

  Background:
    Given a vehicle agent with a mock rule detector and a mock ML predictor

  Scenario: Rule-based detector is used on tick 1
    When the agent processes tick number 1
    Then the rule-based detector should have been called
    And the ML predictor should NOT have been called

  Scenario: Rule-based detector is used on tick 10
    When the agent processes tick number 10
    Then the rule-based detector should have been called
    And the ML predictor should NOT have been called

  Scenario: ML predictor is used on tick 11
    When the agent processes tick number 11
    Then the ML predictor should have been called

  Scenario: ML predictor is used on tick 50
    When the agent processes tick number 50
    Then the ML predictor should have been called

  Scenario: Rule-based detector acts as safety net when ML returns no alerts on tick 11
    Given the ML predictor returns no alerts
    And the rule-based detector returns one alert
    When the agent processes tick number 11
    Then the rule-based detector should have been called
    And the final alert list should not be empty
