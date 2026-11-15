/** Friendly Bluetooth error texts keyed by the server's stable error code (the code is always shown too). */
import { AccountApiError } from '../../api/accountApi';

export const BLE_ERROR: Record<string, string> = {
  bluetooth_dependency_missing: 'The Bluetooth runtime is missing from this AETHER build.',
  bluetooth_adapter_missing: 'No Bluetooth adapter was found on this computer.',
  bluetooth_off: 'Bluetooth is turned off. Turn it on in Windows Settings → Bluetooth & devices, then try again.',
  bluetooth_permission_denied: 'Windows denied access to the Bluetooth radio. Allow it in Settings → Privacy & security → Radios.',
  ble_scan_timeout: 'The Bluetooth scan did not finish in time. Try again.',
  ble_os_error: 'Windows reported a Bluetooth error. Toggle Bluetooth off/on and try again.',
  ble_unavailable: 'Bluetooth is not available on this computer.',
  device_busy: 'This sensor is already in use (another recording, another window, or the legacy sensor path).',
  adapter_limit: 'The software limit of simultaneous sensors is reached. Stop another recording first.',
  device_not_hrs: 'Unsupported device: it does not expose the standard Bluetooth Heart Rate Service (0x180D / 0x2A37).',
  connection_timeout: 'Connection timed out. Wear the strap (moisten the electrodes) and close other apps or phones connected to it.',
  connection_failed: 'The connection failed. Make sure the sensor is awake and not connected to another device.',
  sensor_disconnected: 'The sensor disconnected.',
  simulation_unavailable: 'The simulated test strap is not enabled in this process.',
  storage_unavailable: 'Personal storage is temporarily unavailable; no data was lost that was already saved.',
  unauthenticated: 'Your personal session has ended. Sign in again.',
  not_found: 'This device is not registered to your account.',
  device_exists: 'This sensor is already registered to your account.',
};

export function bleErrorText(error: unknown): { text: string; code: string } {
  if (error instanceof AccountApiError) {
    const code = error.serverCode || error.code;
    return { text: BLE_ERROR[code] ?? error.message, code };
  }
  return { text: error instanceof Error ? error.message : 'The sensor request failed.', code: 'client_error' };
}

