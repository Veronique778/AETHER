"""AETHER CORE-compatible entry point. All calculations live in mission_systems."""
from mission_systems.symbiosis.environment import EnvironmentService, sample_environment
from mission_systems.symbiosis.analysis import trends, relationship, compare_periods
from mission_systems.symbiosis.scenarios import compare_conditions

def symbiosis_summary():
    return 'Environment history, trends and simulated alternatives'
