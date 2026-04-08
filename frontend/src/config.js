// Detect Capacitor native environment
const isNative = typeof window !== 'undefined' &&
  window.Capacitor !== undefined &&
  window.Capacitor.isNativePlatform();

export const API_BASE = isNative
  ? 'https://halcyonlab.app/api'
  : (import.meta.env.VITE_API_URL || '/api');

export const IS_CLOUD = isNative ||
  import.meta.env.VITE_IS_CLOUD === 'true' ||
  API_BASE.includes('render.com') ||
  API_BASE.includes('onrender.com') ||
  API_BASE.includes('halcyonlab.app');

export const API_SECRET = import.meta.env.VITE_API_SECRET || '';
