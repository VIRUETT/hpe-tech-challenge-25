Feature: Pre-failure warm-up labels in training data
  As a ML engineer
  I want the training pipeline to generate normal labels during the warm-up phase
  So that the model learns the stable baseline before the failure onset transition

  Scenario: Normal scenario produces only normal labels
    Given synthetic data is generated for a NORMAL scenario with an AMBULANCE
    Then all labels in the dataset should be "normal"

  Scenario: Failure scenario has normal labels during warm-up
    Given synthetic data is generated for an ENGINE_OVERHEAT scenario with an AMBULANCE
    Then the dataset should contain at least 1 "normal" label
    And the dataset should contain at least 1 "engine_overheat" label

  Scenario: Warm-up rows precede failure rows in the dataset
    Given synthetic data is generated for a BATTERY_DEGRADATION scenario with an AMBULANCE
    Then all "normal" rows should appear before all "battery_degradation" rows in the dataset

  Scenario: Oil pressure drop scenario produces labelled rows
    Given synthetic data is generated for an OIL_PRESSURE_DROP scenario with a FIRE_TRUCK
    Then the dataset should contain at least 1 "oil_pressure_drop" label

  Scenario: Vibration anomaly scenario produces labelled rows
    Given synthetic data is generated for a VIBRATION_ANOMALY scenario with a POLICE vehicle
    Then the dataset should contain at least 1 "vibration_anomaly" label

  Scenario: Brake degradation scenario produces labelled rows
    Given synthetic data is generated for a BRAKE_DEGRADATION scenario with an AMBULANCE
    Then the dataset should contain at least 1 "brake_degradation" label
