import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { SessionDetails } from '../../../api/types';
import { Button, cx, Icon, Notice } from '../../../ui';
import { connected, E, generate, isSolved, minRotations, N, nextSize, rotateMask, S, W, type Grid } from '../logic/orbitFlow';

function TileSvg({ mask, on, core }: { mask: number; on: boolean; core: boolean }) {
  const c = on ? '#9cc9ad' : '#5f7268';
  return (
    <svg viewBox="0 0 40 40" className="h-full w-full" aria-hidden>
      {mask & N ? <line x1="20" y1="20" x2="20" y2="0" stroke={c} strokeWidth="7" strokeLinecap="round" /> : null}
      {mask & E ? <line x1="20" y1="20" x2="40" y2="20" stroke={c} strokeWidth="7" strokeLinecap="round" /> : null}
      {mask & S ? <line x1="20" y1="20" x2="20" y2="40" stroke={c} strokeWidth="7" strokeLinecap="round" /> : null}
      {mask & W ? <line x1="20" y1="20" x2="0" y2="20" stroke={c} strokeWidth="7" strokeLinecap="round" /> : null}
      {on && (mask & N ? <line className="flow-dash" x1="20" y1="20" x2="20" y2="0" stroke="#e3d6bd" strokeWidth="2.2" strokeLinecap="round" /> : null)}
      {on && (mask & E ? <line className="flow-dash" x1="20" y1="20" x2="40" y2="20" stroke="#e3d6bd" strokeWidth="2.2" strokeLinecap="round" /> : null)}
      {on && (mask & S ? <line className="flow-dash" x1="20" y1="20" x2="20" y2="40" stroke="#e3d6bd" strokeWidth="2.2" strokeLinecap="round" /> : null)}
      {on && (mask & W ? <line className="flow-dash" x1="20" y1="20" x2="0" y2="20" stroke="#e3d6bd" strokeWidth="2.2" strokeLinecap="round" /> : null)}
      {core ? <><circle cx="20" cy="20" r="12" fill="#e3d6bd" opacity=".18" /><circle cx="20" cy="20" r="9" fill="#e3d6bd" stroke="#16211c" strokeWidth="2" /></> : <circle cx="20" cy="20" r="5" fill={c} />}
    </svg>
  );
}

export function OrbitFlow({ onReport }: { reducedMotion: boolean; onReport: (d: SessionDetails) => void }) {
  const [size, setSize] = useState(4);
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1e9));
  const [grid, setGrid] = useState<Grid>(() => generate(4, seed));
  const [minMoves, setMinMoves] = useState(() => minRotations(grid));
  const [moves, setMoves] = useState(0);
  const [start, setStart] = useState(() => performance.now());
  const [solvedAt, setSolvedAt] = useState<number | null>(null);
  const [focus, setFocus] = useState(0);
  const [log, setLog] = useState<{ size: number; seconds: number; moves: number; minMoves: number }[]>([]);
  const [advice, setAdvice] = useState<string | null>(null);
  const [now, setNow] = useState(performance.now());
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => { const id = setInterval(() => setNow(performance.now()), 1000); return () => clearInterval(id); }, []);
  useEffect(() => {
    const solved = log.length;
    const totalMoves = log.reduce((s, a) => s + a.moves, 0);
    onReport({ puzzles_solved: solved, last_grid: log.at(-1)?.size ?? size, total_moves: totalMoves, total_seconds: Math.round(log.reduce((s, a) => s + a.seconds, 0)),
      mean_efficiency_pct: solved ? Math.round((log.reduce((s, a) => s + a.minMoves / Math.max(1, a.moves), 0) / solved) * 100) : null });
  }, [log, size, onReport]);

  const lit = connected(grid);
  const rotate = (i: number, dir = 1) => {
    if (solvedAt != null) return;
    const tiles = [...grid.tiles];
    tiles[i] = rotateMask(tiles[i], dir === 1 ? 1 : 3);
    const g = { ...grid, tiles };
    setGrid(g);
    setMoves((m) => m + 1);
    if (isSolved(g)) {
      const t = performance.now();
      setSolvedAt(t);
      const attempt = { size: g.size, seconds: (t - start) / 1000, moves: moves + 1, minMoves };
      setLog((l) => [...l, attempt]);
      const n = nextSize(attempt);
      setAdvice(n.reason);
      setSize(n.size);
    }
  };
  const newPuzzle = (s = size) => {
    const sd = Math.floor(Math.random() * 1e9);
    const g = generate(s, sd);
    setSeed(sd); setGrid(g); setMinMoves(minRotations(g)); setMoves(0); setStart(performance.now()); setSolvedAt(null); setFocus(0); setAdvice(null);
  };
  const onKey = (e: KeyboardEvent, i: number) => {
    const n = grid.size;
    const x = i % n, y = Math.floor(i / n);
    let j = i;
    if (e.key === 'ArrowRight') j = y * n + Math.min(n - 1, x + 1);
    else if (e.key === 'ArrowLeft') j = y * n + Math.max(0, x - 1);
    else if (e.key === 'ArrowDown') j = Math.min(n - 1, y + 1) * n + x;
    else if (e.key === 'ArrowUp') j = Math.max(0, y - 1) * n + x;
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); rotate(i, e.shiftKey ? -1 : 1); return; }
    else return;
    e.preventDefault();
    setFocus(j);
    refs.current[j]?.focus();
  };
  const elapsed = ((solvedAt ?? now) - start) / 1000;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="always-dark relative flex flex-col items-center overflow-hidden rounded-2xl bg-[radial-gradient(ellipse_at_center,#1a2c22_0%,#0d1612_70%)] p-4">
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 400 300" preserveAspectRatio="none" aria-hidden="true">
          {[60, 100, 140].map((r) => <ellipse key={r} cx="200" cy="150" rx={r * 1.4} ry={r} fill="none" stroke="#5f7268" strokeOpacity=".35" strokeDasharray="2 6" />)}
        </svg>
        <div className="relative mb-2 w-full max-w-[460px]">
          <div className="flex items-center justify-between text-xs text-[#b9c7bd]"><span>Flow to core</span><span className="tabular">{Math.round((lit.size / grid.tiles.length) * 100)}%</span></div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#27392f]" aria-hidden="true"><div className="h-full rounded-full bg-[#9cc9ad] transition-[width] duration-500" style={{ width: `${(lit.size / grid.tiles.length) * 100}%` }} /></div>
        </div>
        <div role="grid" aria-label={`Orbit Flow puzzle, ${grid.size} by ${grid.size}. Rotate tiles to connect every conduit to the core.`}
          className="relative grid w-full max-w-[460px] gap-1 rounded-2xl border border-line bg-moss-900/80 p-2 backdrop-blur-sm" style={{ gridTemplateColumns: `repeat(${grid.size}, minmax(0, 1fr))` }}>
          {grid.tiles.map((m, i) => (
            <button key={`${seed}-${i}`} ref={(el) => { refs.current[i] = el; }} type="button" role="gridcell" tabIndex={focus === i ? 0 : -1}
              aria-label={`Tile row ${Math.floor(i / grid.size) + 1}, column ${(i % grid.size) + 1}${i === grid.source ? ', core' : ''}, ${lit.has(i) ? 'connected' : 'not connected'}`}
              onClick={(e) => { setFocus(i); rotate(i, e.shiftKey ? -1 : 1); }} onContextMenu={(e) => { e.preventDefault(); rotate(i, -1); }} onKeyDown={(e) => onKey(e, i)}
              className={cx('aspect-square rounded-lg transition-colors', lit.has(i) ? 'bg-moss-700' : 'bg-moss-800 hover:bg-moss-700/70')}>
              <TileSvg mask={m} on={lit.has(i)} core={i === grid.source} />
            </button>
          ))}
        </div>
        {solvedAt != null && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden="true">
            <span className="h-40 w-40 rounded-full border-2 border-[#e3d6bd]" style={{ animation: 'aether-ring 1.4s ease-out 2' }} />
          </div>
        )}
        <p className="relative mt-2 text-xs text-[#b9c7bd]">Click or Enter rotates clockwise · Shift+click / right-click / Shift+Enter rotates back · arrow keys move</p>
      </div>
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-xl border border-line p-2"><div className="text-xs text-ink-3">Grid</div><div className="tabular text-lg font-semibold text-calm">{grid.size}×{grid.size}</div></div>
          <div className="rounded-xl border border-line p-2"><div className="text-xs text-ink-3">Moves</div><div className="tabular text-lg font-semibold text-calm">{moves}</div></div>
          <div className="rounded-xl border border-line p-2"><div className="text-xs text-ink-3">Time</div><div className="tabular text-lg font-semibold text-calm">{Math.floor(elapsed / 60)}:{String(Math.floor(elapsed % 60)).padStart(2, '0')}</div></div>
        </div>
        <div className="text-sm text-ink-2">Connected: <span className="tabular text-ink">{lit.size}/{grid.tiles.length}</span> tiles</div>
        {solvedAt != null ? (
          <Notice tone="good" title="Flow restored">
            Solved in {moves} moves (minimum {minMoves}). {advice}
            <div className="mt-2"><Button size="sm" variant="primary" icon="arrowRight" onClick={() => newPuzzle()}>Next puzzle ({size}×{size})</Button></div>
          </Notice>
        ) : <Button size="sm" icon="reset" onClick={() => newPuzzle(grid.size)}>New puzzle, same size</Button>}
        {log.length > 0 && (
          <div>
            <div className="eyebrow mb-1">This session</div>
            <ul className="space-y-1 text-sm text-ink-2">{log.map((a, i) => <li key={i} className="tabular flex items-center gap-2"><Icon name="checkCircle" size={14} className="text-good" />{a.size}×{a.size} · {a.moves} moves · {Math.round(a.seconds)} s</li>)}</ul>
          </div>
        )}
        <p className="text-xs text-ink-3">Difficulty adapts after each solve using time and move efficiency. No timers pressure you – there is no fail state.</p>
      </div>
    </div>
  );
}
