"""TEST-ENVIRONMENT SHIM for `argon2-cffi` (Backend №3, 03A) — NEVER used in production.

The build container has no network and no argon2-cffi wheel, so Backend №2's app.auth cannot be imported. This shim
implements the small part of the argon2-cffi API that app.auth uses (PasswordHasher.hash / verify, Type.ID,
VerificationError, VerifyMismatchError, InvalidHashError) with a REAL Argon2id key derivation from `cryptography`
(≥ 44), producing standard PHC strings ($argon2id$v=19$m=…,t=…,p=…$salt$hash). It is activated only through the
pytest plugin tests/be3_argon2_env.py and only when argon2-cffi is not installed. Production must install argon2-cffi.
"""
from __future__ import annotations

import base64
import hmac
import os
import types
from enum import Enum

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id


class Type(Enum):
    D = 0
    I = 1
    ID = 2


class VerificationError(Exception):
    pass


class VerifyMismatchError(VerificationError):
    pass


class InvalidHashError(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode().rstrip('=')


def _unb64(s: str) -> bytes:
    return base64.b64decode(s + '=' * (-len(s) % 4))


class PasswordHasher:
    def __init__(self, time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, encoding='utf-8', type=Type.ID):
        if type is not Type.ID:
            raise ValueError('shim supports Argon2id only')
        self.t, self.m, self.p, self.hash_len, self.salt_len, self.encoding = time_cost, memory_cost, parallelism, hash_len, salt_len, encoding

    def _derive(self, password, salt, t, m, p, n):
        pw = password.encode(self.encoding) if isinstance(password, str) else password
        return Argon2id(salt=salt, length=n, iterations=t, lanes=p, memory_cost=m).derive(pw)

    def hash(self, password) -> str:
        salt = os.urandom(self.salt_len)
        h = self._derive(password, salt, self.t, self.m, self.p, self.hash_len)
        return f'$argon2id$v=19$m={self.m},t={self.t},p={self.p}${_b64(salt)}${_b64(h)}'

    def verify(self, encoded, password) -> bool:
        try:
            _, alg, ver, params, salt, digest = encoded.split('$')
            if alg != 'argon2id' or ver != 'v=19':
                raise ValueError
            kv = dict(x.split('=') for x in params.split(','))
            salt_b, want = _unb64(salt), _unb64(digest)
            got = self._derive(password, salt_b, int(kv['t']), int(kv['m']), int(kv['p']), len(want))
        except (ValueError, KeyError, AttributeError) as exc:
            raise InvalidHashError('invalid argon2 hash') from exc
        if not hmac.compare_digest(got, want):
            raise VerifyMismatchError('password does not match')
        return True


exceptions = types.SimpleNamespace(VerificationError=VerificationError, VerifyMismatchError=VerifyMismatchError,
                                   InvalidHashError=InvalidHashError)
