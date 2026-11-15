/**
 * Windows download — the ONLY place to change the release link and metadata.
 *
 * WINDOWS_DOWNLOAD_URL: paste the public itch.io (or other) page here, e.g. 'https://<your-user>.itch.io/aether'.
 * While it is empty the site shows "Download coming soon" instead of a button that leads nowhere.
 * Only https:// links are accepted (see downloadAvailable()).
 */
export const WINDOWS_DOWNLOAD_URL = '';

export const APP_VERSION = '1.5.0 (Unified source — rebuild pending)';
export const PLATFORM = 'Windows 10/11 x64 · latest build pending';
/** Shown verbatim next to the download. Keep it honest. */
export const RELEASE_STATUS = 'Research prototype · unified desktop update awaiting verified OS-specific binaries';

/** File name and SHA-256 of the published ZIP. Replace both whenever you upload a different file. Empty → hidden. */
export const DOWNLOAD_FILE_NAME = '';
export const DOWNLOAD_SHA256 = '';
export const DOWNLOAD_SIZE_MB = 0;

export function downloadAvailable(url: string = WINDOWS_DOWNLOAD_URL): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && !!u.hostname && !u.username && !u.password;
  } catch {
    return false;
  }
}
