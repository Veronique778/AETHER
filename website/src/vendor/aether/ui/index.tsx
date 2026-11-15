/** Minimal subset of the AETHER UI kit needed by the vendored 3D viewport (no router / API dependencies). */
export { Icon, type IconName } from './Icon';
export { Dialog, Tooltip, InfoTip } from './overlay';

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ');
}
