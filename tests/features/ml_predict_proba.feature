Feature: ML predictor returns real class probabilities
  As a ML engineer
  I want the Predictor to use predict_proba() for failure_probability and confidence
  So that alert probabilities reflect true model uncertainty rather than hard-coded constants

  Scenario: Predictor failure_probability is derived from predict_proba output
    Given a trained mock RandomForest model with predict_proba returning 0.72 for a class
    When the Predictor analyzes telemetry and the model predicts that class
    Then the resulting alert failure_probability should equal 0.72

  Scenario: Predictor confidence is capped at 0.99
    Given a trained mock RandomForest model with predict_proba returning 0.999 for a class
    When the Predictor analyzes telemetry and the model predicts that class
    Then the resulting alert confidence should be less than or equal to 0.99

  Scenario: Predictor confidence has a minimum floor of 0.50
    Given a trained mock RandomForest model with predict_proba returning 0.10 for a class
    When the Predictor analyzes telemetry and the model predicts that class
    Then the resulting alert confidence should be greater than or equal to 0.50

  Scenario: Normal prediction produces no alerts
    Given a trained mock RandomForest model that always predicts "normal"
    When the Predictor analyzes telemetry with a full feature window
    Then no alerts should be produced

  Scenario: Engine overheat prediction produces a CRITICAL alert
    Given a trained mock RandomForest model that predicts "engine_overheat" with probability 0.85
    When the Predictor analyzes telemetry with a full feature window
    Then a CRITICAL severity alert should be produced
    And the alert failure_probability should equal 0.85
