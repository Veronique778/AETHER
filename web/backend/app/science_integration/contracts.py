"""Schemas for additive candidate endpoints; payload semantics await BE3 review."""
from app.api_contract_15 import obj, paged, schema, Analysis, STRING, BOOLEAN

NULL_STRING = {'type': ['string', 'null']}


def analysis_schema():
    value = schema(Analysis)
    value['properties'].update({
        'status': {'enum': ['ok', 'insufficient_data']},
        'provenance': {'type': 'array', 'items': obj({'id': STRING, 'origin': {'enum': ['real', 'manual', 'simulated']},
                'source': STRING, 'quality': STRING, 'missing': BOOLEAN, 'processing_version': STRING})}})
    value['required'] += ['status', 'provenance']
    value['additionalProperties'] = False
    return value


def response(method, path):
    if path == '/api/signals':
        return obj({'contract_status': {'const': 'integration_candidate'},
                    'catalog_source': {'const': 'be2_measurement_validation'},
                    'items': {'type': 'array', 'items': obj({'signal': STRING, 'unit': STRING, 'minimum': {'type': 'number'}, 'maximum': {'type': 'number'}})}})
    if path == '/api/phantom-analyses':
        if method == 'POST': return obj({'analysis': analysis_schema(), 'created': BOOLEAN})
        item = analysis_schema(); item['properties']['seq'] = {'type': 'integer'}; item['required'].append('seq')
        return paged(item)
    if path == '/api/phantom-analyses/{analysis_id}': return analysis_schema()
    if path == '/api/admin/users':
        return paged(obj({'seq': {'type': 'integer'}, 'id': STRING, 'login': STRING, 'role': {'enum': ['astronaut', 'administrator']},
                          'active': BOOLEAN, 'created_at': STRING, 'astronaut_id': STRING, 'display_name': STRING}))
    if path == '/api/admin/users/{id}':
        return obj({'id': STRING, 'active': BOOLEAN, 'role': {'enum': ['astronaut', 'administrator']}})
    if path == '/api/admin/audit-logs':
        return paged(obj({'seq': {'type': 'integer'}, 'id': {'type': 'integer'}, 'created_at': STRING, 'actor_id': NULL_STRING,
                          'action': STRING, 'resource_type': STRING, 'resource_id': NULL_STRING, 'outcome': STRING}))
    if path == '/api/measurements/batch':
        from app.api_contract_15 import response as original_response
        return obj({'items': {'type': 'array', 'items': original_response('POST', '/api/measurements')}})
    return None
