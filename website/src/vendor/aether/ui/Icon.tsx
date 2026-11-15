import type { CSSProperties } from 'react';
/**
 * Local stroke icon set (24×24, 1.75 stroke) drawn for AETHER in a Lucide-like style,
 * so the app has no runtime icon dependency. Replace with lucide-react by mapping names.
 */
const P = {
  compass: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M15.5 8.5l-2 5-5 2 2-5 5-2Z',
  ship: 'M3 12h3l2-3h8l2 3h3 M6 12l2 3h8l2-3 M10 9V6h4v3 M12 15v3',
  body: 'M12 6.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z M7 9.5h10 M12 9.5v6 M12 15.5l-3 6 M12 15.5l3 6 M7 9.5l-2 5 M17 9.5l2 5',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  brain: 'M9 4a3 3 0 0 0-3 3v.5A3 3 0 0 0 4 10.3 3 3 0 0 0 5 15a3 3 0 0 0 4 4.5V4Z M15 4a3 3 0 0 1 3 3v.5a3 3 0 0 1 2 2.8 3 3 0 0 1-1 4.7 3 3 0 0 1-4 4.5V4Z',
  waves: 'M3 8c2-2 4-2 6 0s4 2 6 0 4-2 6 0 M3 13c2-2 4-2 6 0s4 2 6 0 4-2 6 0 M3 18c2-2 4-2 6 0s4 2 6 0 4-2 6 0',
  users: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z M2.5 20a6.5 6.5 0 0 1 13 0 M16 4.3a3.5 3.5 0 0 1 0 6.4 M18 14.5a6 6 0 0 1 3.5 5.5',
  leaf: 'M5 19c0-8 5-13 15-14-1 10-6 15-14 15 M5 19l7-7',
  orbit: 'M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z M20.5 12c0 2.5-3.8 4.5-8.5 4.5S3.5 14.5 3.5 12 7.3 7.5 12 7.5s8.5 2 8.5 4.5Z M18.5 5.5l1 1',
  flask: 'M9 3h6 M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3 M7.5 15h9',
  heart: 'M12 20s-7.5-4.4-7.5-10A4.3 4.3 0 0 1 12 7a4.3 4.3 0 0 1 7.5 3c0 5.6-7.5 10-7.5 10Z',
  moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z',
  gauge: 'M4 18a8.5 8.5 0 1 1 16 0 M12 14l4-5 M12 15a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z',
  zap: 'M13 3L5 13h6l-1 8 8-10h-6l1-8Z',
  thermo: 'M14 14.8V5a2 2 0 1 0-4 0v9.8a4 4 0 1 0 4 0Z M12 17V9',
  droplet: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z',
  wind: 'M3 9h11a3 3 0 1 0-3-3 M3 15h15a3 3 0 1 1-3 3 M3 12h8',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4',
  alert: 'M12 4l9 16H3l9-16Z M12 10v4 M12 17h.01',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 11v5 M12 8h.01',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  checkCircle: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M8 12.5l3 3 5-6',
  x: 'M6 6l12 12 M18 6L6 18',
  play: 'M7 4.5v15l12-7.5-12-7.5Z',
  pause: 'M8 5v14 M16 5v14',
  reset: 'M4 4v6h6 M4.5 15a8 8 0 1 0 1.8-8.3L4 10',
  chevronRight: 'M9 5l7 7-7 7',
  chevronLeft: 'M15 5l-7 7 7 7',
  chevronDown: 'M5 9l7 7 7-7',
  plus: 'M12 5v14 M5 12h14',
  minus: 'M5 12h14',
  rotate: 'M20 12a8 8 0 1 1-2.3-5.7 M20 4v4h-4',
  download: 'M12 4v11 M7 10l5 5 5-5 M5 20h14',
  printer: 'M7 9V3h10v6 M7 17H4v-7h16v7h-3 M7 14h10v7H7v-7Z',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M4 21a8 8 0 0 1 16 0',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 7v5l3 2',
  calendar: 'M4 6h16v15H4V6Z M4 10h16 M8 3v4 M16 3v4',
  database: 'M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3Z M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5 M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  bluetooth: 'M7 7l10 10-5 4V3l5 4L7 17',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  lock: 'M6 11h12v10H6V11Z M8 11V7a4 4 0 0 1 8 0v4',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  sliders: 'M4 6h10 M18 6h2 M4 12h4 M12 12h8 M4 18h12 M20 18h0 M16 4v4 M10 10v4 M18 16v4',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  sparkles: 'M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8L12 3Z M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z',
  mountain: 'M3 20l6-10 4 6 3-4 5 8H3Z M9 10l2-3',
  puzzle: 'M10 4a2 2 0 1 1 4 0v2h4v4h-2a2 2 0 1 0 0 4h2v4h-4v-2a2 2 0 1 0-4 0v2H6v-4h2a2 2 0 1 0 0-4H6V6h4V4Z',
  timer: 'M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z M12 9v4l2 2 M9 2h6',
  layers: 'M12 3l9 5-9 5-9-5 9-5Z M3 13l9 5 9-5 M3 17l9 5 9-5',
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M12 12.5a.5.5 0 1 0 0-1 .5.5 0 0 0 0 1Z',
  table: 'M4 5h16v14H4V5Z M4 10h16 M4 15h16 M10 5v14',
  arrowRight: 'M5 12h14 M13 6l6 6-6 6',
  arrowUp: 'M12 19V5 M6 11l6-6 6 6',
  arrowDown: 'M12 5v14 M6 13l6 6 6-6',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z',
  bell: 'M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9 M10.3 21a1.94 1.94 0 0 0 3.4 0',
  grip: 'M9 6h.01 M15 6h.01 M9 12h.01 M15 12h.01 M9 18h.01 M15 18h.01',
  expand: 'M15 3h6v6 M9 21H3v-6 M21 3l-7 7 M3 21l7-7',
  wifiOff: 'M2 2l20 20 M8.5 16.4a5 5 0 0 1 7 0 M5 12.9a10 10 0 0 1 5.2-2.8 M19 12.9a10 10 0 0 0-2.4-1.8 M2 8.8a15 15 0 0 1 4.2-2.6 M22 8.8a15 15 0 0 0-11.3-3.8 M12 20h.01',
} satisfies Record<string, string>;

export type IconName = keyof typeof P;

export function Icon({ name, size = 18, className, title, strokeWidth = 1.75, style }: { name: IconName; size?: number; className?: string; title?: string; strokeWidth?: number; style?: CSSProperties }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      <path d={P[name]} />
    </svg>
  );
}
