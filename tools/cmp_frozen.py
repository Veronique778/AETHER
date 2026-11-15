import sys, os, json
sys.path.insert(0, '/home/claude/tools')
from pyi_archive import CArchive, PYZ
exe, *roots = sys.argv[1:]
a = CArchive(exe)
p = PYZ(a.extract([x for x in a.entries if x['name']=='PYZ.pyz'][0]))
def norm(co):
    consts = tuple(norm(c) if hasattr(c, 'co_code') else (repr(c) if not isinstance(c, (frozenset,)) else repr(sorted(map(repr,c)))) for c in co.co_consts)
    return (co.co_name, co.co_qualname, co.co_code, consts, co.co_names, co.co_varnames, co.co_freevars, co.co_cellvars, co.co_argcount, co.co_kwonlyargcount, co.co_flags)
def find_src(mod, typ):
    rel = mod.replace('.', '/')
    for r in roots:
        for cand in ([f'{r}/{rel}/__init__.py'] if typ in (1,) else []) + [f'{r}/{rel}.py', f'{r}/{rel}/__init__.py']:
            if os.path.exists(cand): return cand
    return None
res = {}
mods = [n for n in p.toc if n.split('.')[0] in ('app', 'mission_systems', 'desktop_native', 'release_smoke')]
for m in sorted(mods):
    typ, code = p.code(m)
    src = find_src(m, typ)
    if not src: res[m] = 'MISSING_IN_SOURCE'; continue
    try:
        c2 = compile(open(src, 'rb').read(), src, 'exec')
    except Exception as e:
        res[m] = f'COMPILE_ERROR {e}'; continue
    res[m] = ('IDENTICAL' if norm(code) == norm(c2) else 'DIFFERS') + ' ' + os.path.relpath(src, '/home/claude/handoff')
# desktop_native is a script entry in CArchive
for e in a.entries:
    if e['name'] == 'desktop_native':
        import marshal
        co = marshal.loads(a.extract(e))
        for r in roots:
            s = os.path.join(r, '..', '..', 'desktop_native.py')
            if os.path.exists(s):
                res['<script>desktop_native'] = ('IDENTICAL' if norm(co) == norm(compile(open(s,'rb').read(), s, 'exec')) else 'DIFFERS') + ' ' + s
for k, v in res.items(): print(f'{v.split()[0]:18} {k}  {" ".join(v.split()[1:])}')
