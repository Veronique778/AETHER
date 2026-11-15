"""Canonical persistence factory for BE3_03A."""
def science_storage():
    from .science_adapter_06 import CanonicalScienceStorage
    return CanonicalScienceStorage()
