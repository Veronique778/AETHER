"""Minimal PyInstaller 6.x CArchive / PYZ reader+writer (no PyInstaller dependency).

Used to (a) audit what is frozen inside AETHER_1_5.exe and (b) repackage the
existing Windows bootloader with updated pure-Python modules compiled by the
same CPython minor version (3.13).
"""
import marshal
import struct
import sys
import zlib

COOKIE_MAGIC = b"MEI\014\013\012\013\016"
COOKIE_FMT = "!8sIIII64s"
COOKIE_SIZE = struct.calcsize(COOKIE_FMT)
ENTRY_FMT = "!IIIIBc"
ENTRY_SIZE = struct.calcsize(ENTRY_FMT)


class CArchive:
    def __init__(self, path):
        self.path = path
        self.data = open(path, "rb").read()
        idx = self.data.rfind(COOKIE_MAGIC)
        if idx < 0:
            raise ValueError("no PyInstaller cookie")
        self.cookie_pos = idx
        (_m, self.pkg_len, self.toc_off, self.toc_len, self.pyvers,
         self.pylib) = struct.unpack(COOKIE_FMT, self.data[idx:idx + COOKIE_SIZE])
        self.pkg_start = idx + COOKIE_SIZE - self.pkg_len
        self.entries = []
        pos = self.pkg_start + self.toc_off
        end = pos + self.toc_len
        while pos < end:
            elen, doff, dlen, ulen, cflag, tc = struct.unpack(ENTRY_FMT, self.data[pos:pos + ENTRY_SIZE])
            name = self.data[pos + ENTRY_SIZE:pos + elen].rstrip(b"\0").decode("utf-8")
            self.entries.append(dict(name=name, off=doff, dlen=dlen, ulen=ulen, cflag=cflag, tc=tc.decode()))
            pos += elen
        self.tail = self.data[idx + COOKIE_SIZE:]

    @property
    def bootloader(self):
        return self.data[:self.pkg_start]

    def raw(self, e):
        return self.data[self.pkg_start + e["off"]:self.pkg_start + e["off"] + e["dlen"]]

    def extract(self, e):
        b = self.raw(e)
        return zlib.decompress(b) if e["cflag"] else b


class PYZ:
    def __init__(self, blob):
        assert blob[:4] == b"PYZ\0", blob[:4]
        self.pymagic = blob[4:8]
        (toc_off,) = struct.unpack("!i", blob[8:12])
        toc = marshal.loads(blob[toc_off:])
        if isinstance(toc, list):
            toc = dict(toc)
        self.toc = toc
        self.blob = blob

    def get(self, name):
        typ, off, length = self.toc[name]
        if length == 0:                                   # namespace packages carry no code object
            return typ, None
        return typ, zlib.decompress(self.blob[off:off + length])

    def code(self, name):
        typ, raw = self.get(name)
        return typ, marshal.loads(raw)


def build_pyz(pymagic, entries):
    """entries: list of (name, typ, raw_marshalled_bytes)."""
    out = bytearray(b"PYZ\0" + pymagic + b"\0\0\0\0")
    toc = []
    for name, typ, raw in entries:
        if raw is None:                                   # namespace package: zero-length entry, as PyInstaller writes it
            toc.append((name, (typ, len(out), 0)))
            continue
        comp = zlib.compress(raw, 9)
        toc.append((name, (typ, len(out), len(comp))))
        out += comp
    toc_off = len(out)
    out += marshal.dumps(toc)
    out[8:12] = struct.pack("!i", toc_off)
    return bytes(out)


def build_carchive(bootloader, items, pyvers, pylib, tail=b""):
    """items: list of dict(name, tc, payload(bytes uncompressed or raw), cflag, ulen, raw)"""
    body = bytearray()
    toc = bytearray()
    for it in items:
        data = it["raw"]
        off = len(body)
        body += data
        nm = it["name"].encode("utf-8") + b"\0"
        elen = ENTRY_SIZE + len(nm)
        pad = (16 - elen % 16) % 16
        nm += b"\0" * pad
        elen += pad
        toc += struct.pack(ENTRY_FMT, elen, off, len(data), it["ulen"], it["cflag"], it["tc"].encode()) + nm
    toc_off = len(body)
    pkg_len = len(body) + len(toc) + COOKIE_SIZE
    cookie = struct.pack(COOKIE_FMT, COOKIE_MAGIC, pkg_len, toc_off, len(toc), pyvers, pylib)
    return bootloader + bytes(body) + bytes(toc) + cookie + tail


if __name__ == "__main__":
    a = CArchive(sys.argv[1])
    print("pyvers", a.pyvers, "pylib", a.pylib.rstrip(b"\0"), "bootloader bytes", a.pkg_start, "tail", len(a.tail))
    for e in a.entries:
        print(e["tc"], e["cflag"], e["dlen"], e["ulen"], e["name"])
