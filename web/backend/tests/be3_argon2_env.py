"""pytest plugin (opt-in): `python -m pytest -p be3_argon2_env ...`

If argon2-cffi is installed, does nothing. Otherwise registers tests/fakes/argon2_cryptography_shim.py as `argon2`
(REAL Argon2id from `cryptography`) so Backend №2's app.auth can be imported in an offline test environment.
The TEST_REPORT states every run that used it. Never imported by application code.
"""
import importlib.util
import sys
import types

if importlib.util.find_spec('argon2') is None:
    sys.path.insert(0, __import__('os').path.dirname(__file__))
    from fakes import argon2_cryptography_shim as shim
    mod = types.ModuleType('argon2')
    for name in ('PasswordHasher', 'Type', 'VerificationError', 'VerifyMismatchError', 'InvalidHashError'):
        setattr(mod, name, getattr(shim, name))
    exc = types.ModuleType('argon2.exceptions')
    for name in ('VerificationError', 'VerifyMismatchError', 'InvalidHashError'):
        setattr(exc, name, getattr(shim, name))
    mod.exceptions = exc
    mod.__aether_test_shim__ = True
    sys.modules['argon2'] = mod
    sys.modules['argon2.exceptions'] = exc
