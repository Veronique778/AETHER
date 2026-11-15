/**
 * Orbit Flow – rotate tiles so every conduit connects back to the central core.
 * Pure logic: generation (random spanning tree ⇒ always solvable), rotation,
 * solved check and adaptive difficulty.
 */
import { Mulberry32 } from '../../../lib/random';

export const N = 1, E = 2, S = 4, W = 8;
export type Grid = { size: number; tiles: number[]; solution: number[]; source: number };

export function rotateMask(mask: number, times = 1): number {
  let m = mask;
  for (let i = 0; i < ((times % 4) + 4) % 4; i++) m = ((m << 1) | (m >> 3)) & 15;
  return m;
}

const DIRS: [number, number, number, number][] = [[0, -1, N, S], [1, 0, E, W], [0, 1, S, N], [-1, 0, W, E]];

export function generate(size: number, seed: number): Grid {
  const rng = new Mulberry32(seed);
  const solution = new Array<number>(size * size).fill(0);
  const source = Math.floor(size / 2) * size + Math.floor(size / 2);
  const visited = new Set<number>([source]);
  const stack = [source];
  while (stack.length) {
    const cur = stack[stack.length - 1];
    const x = cur % size, y = Math.floor(cur / size);
    const options = DIRS.filter(([dx, dy]) => {
      const nx = x + dx, ny = y + dy;
      return nx >= 0 && ny >= 0 && nx < size && ny < size && !visited.has(ny * size + nx);
    });
    if (!options.length) { stack.pop(); continue; }
    const [dx, dy, bit, opp] = options[Math.floor(rng.next() * options.length)];
    const nxt = (y + dy) * size + (x + dx);
    solution[cur] |= bit;
    solution[nxt] |= opp;
    visited.add(nxt);
    stack.push(nxt);
  }
  const tiles = solution.map((m) => rotateMask(m, Math.floor(rng.next() * 4)));
  // Never start already solved.
  if (isSolved({ size, tiles, source })) {
    const i = tiles.findIndex((m) => rotateMask(m, 1) !== m);
    if (i >= 0) tiles[i] = rotateMask(tiles[i], 1);
  }
  return { size, tiles, solution, source };
}

/** Tiles reachable from the source through matching connections. */
export function connected(g: Pick<Grid, 'size' | 'tiles' | 'source'>): Set<number> {
  const seen = new Set<number>([g.source]);
  const q = [g.source];
  while (q.length) {
    const cur = q.shift()!;
    const x = cur % g.size, y = Math.floor(cur / g.size);
    for (const [dx, dy, bit, opp] of DIRS) {
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= g.size || ny >= g.size) continue;
      const n = ny * g.size + nx;
      if (seen.has(n) || !(g.tiles[cur] & bit) || !(g.tiles[n] & opp)) continue;
      seen.add(n);
      q.push(n);
    }
  }
  return seen;
}

export function isSolved(g: Pick<Grid, 'size' | 'tiles' | 'source'>): boolean {
  if (connected(g).size !== g.size * g.size) return false;
  // No open ends: every connector must have a partner (edges of the board included).
  for (let i = 0; i < g.tiles.length; i++) {
    const x = i % g.size, y = Math.floor(i / g.size);
    for (const [dx, dy, bit, opp] of DIRS) {
      if (!(g.tiles[i] & bit)) continue;
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= g.size || ny >= g.size) return false;
      if (!(g.tiles[ny * g.size + nx] & opp)) return false;
    }
  }
  return true;
}

/** Minimum clockwise rotations to reach the reference solution (lower bound on moves). */
export function minRotations(g: Grid): number {
  return g.tiles.reduce((sum, m, i) => {
    for (let r = 0; r < 4; r++) if (rotateMask(m, r) === g.solution[i]) return sum + r;
    return sum;
  }, 0);
}

export type Attempt = { size: number; seconds: number; moves: number; minMoves: number };

/** Adaptive difficulty: grow after a fluent solve, shrink after a laboured one. */
export function nextSize(a: Attempt, min = 3, max = 8): { size: number; reason: string } {
  const efficiency = a.minMoves / Math.max(a.moves, 1);
  const fast = a.seconds < 20 + a.size * a.size * 2;
  if (fast && efficiency >= 0.45) return { size: Math.min(max, a.size + 1), reason: 'Fluent solve – grid grows by one.' };
  if (a.seconds > 60 + a.size * a.size * 6 || efficiency < 0.2) return { size: Math.max(min, a.size - 1), reason: 'Longer solve – grid shrinks to keep it restful.' };
  return { size: a.size, reason: 'Comfortable pace – same grid size.' };
}
