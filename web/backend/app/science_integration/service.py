"""One science service for both HTTP servers. No Backend #3 code is bundled.

A trusted startup integration must install a reviewed Provider implementation.
No import guessing, request-controlled modules, fallback simulation or math here.
"""
from typing import Protocol
from pydantic import ValidationError
from app.schemas_integration import ScienceResult
from app.persistence.common import APIError
from app.schemas_15 import SIGNALS
from app.schemas_integration import PhantomRequest
from app.storage.api import StorageAPI


class Provider(Protocol):
    def evaluate(self, measurements: list[dict]) -> dict:
        """Return ScienceResult; report insufficient_data without fabricating inputs."""
        ...


# Populated only by trusted application startup after the BE3 binding is reviewed.
# Tests replace this mapping with explicitly labelled test-only providers.
PROVIDERS: dict[str, Provider] = {}


def signals():
    return {'contract_status': 'integration_candidate', 'catalog_source': 'be2_measurement_validation',
            'items': [{'signal': key, 'unit': unit, 'minimum': lo, 'maximum': hi}
                      for key, (unit, lo, hi) in SIGNALS.items()]}


def run(token, body):
    body = PhantomRequest.model_validate(body).model_dump()
    storage = StorageAPI(token)
    snapshot = storage.prepare_analysis(body)
    old = storage.find_analysis(snapshot)
    if old: return {'analysis': old, 'created': False}
    provider = PROVIDERS.get(body['algorithm'])
    if provider is None:
        raise APIError(503, 'science_not_integrated', 'Reviewed Backend #3 provider and package 02A are not installed')
    result = provider.evaluate(snapshot.measurements())
    try:
        result = ScienceResult.model_validate(result).model_dump()
    except (ValidationError, ValueError, TypeError):
        raise APIError(502, 'science_invalid_result', 'Scientific provider returned an invalid result envelope') from None
    saved, created = storage.save_analysis(snapshot, result)
    return {'analysis': saved, 'created': created}
