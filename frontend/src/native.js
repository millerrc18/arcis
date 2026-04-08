/**
 * Native bridge — wraps Capacitor plugins with web fallbacks.
 * Every function is safe to call on web (no-op or graceful fallback).
 */

export function isNative() {
  return typeof window !== 'undefined' &&
    window.Capacitor?.isNativePlatform() === true;
}

export async function hapticTap() {
  if (!isNative()) return;
  try {
    const { Haptics, ImpactStyle } = await import('@capacitor/haptics');
    await Haptics.impact({ style: ImpactStyle.Light });
  } catch {}
}

export async function hapticSuccess() {
  if (!isNative()) return;
  try {
    const { Haptics, NotificationType } = await import('@capacitor/haptics');
    await Haptics.notification({ type: NotificationType.Success });
  } catch {}
}

export async function hapticWarning() {
  if (!isNative()) return;
  try {
    const { Haptics, NotificationType } = await import('@capacitor/haptics');
    await Haptics.notification({ type: NotificationType.Warning });
  } catch {}
}

export async function configureStatusBar() {
  if (!isNative()) return;
  try {
    const { StatusBar, Style } = await import('@capacitor/status-bar');
    await StatusBar.setStyle({ style: Style.Dark });
    await StatusBar.setBackgroundColor({ color: '#050507' });
  } catch {}
}

export async function getStoredToken() {
  if (!isNative()) return localStorage.getItem('hl_token');
  try {
    const { Preferences } = await import('@capacitor/preferences');
    const { value } = await Preferences.get({ key: 'hl_token' });
    return value;
  } catch {
    return localStorage.getItem('hl_token');
  }
}

export async function setStoredToken(token) {
  if (!isNative()) {
    localStorage.setItem('hl_token', token);
    return;
  }
  try {
    const { Preferences } = await import('@capacitor/preferences');
    await Preferences.set({ key: 'hl_token', value: token });
  } catch {
    localStorage.setItem('hl_token', token);
  }
}

export function onAppStateChange(callback) {
  if (!isNative()) return () => {};
  import('@capacitor/app').then(({ App }) => {
    App.addListener('appStateChange', callback);
  });
  return () => {
    import('@capacitor/app').then(({ App }) => {
      App.removeAllListeners();
    });
  };
}
