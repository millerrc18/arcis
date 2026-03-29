export const API_BASE = import.meta.env.VITE_API_URL || '/api';
export const IS_CLOUD = import.meta.env.VITE_IS_CLOUD === 'true' ||
  API_BASE.includes('render.com') || API_BASE.includes('onrender.com') ||
  API_BASE.includes('halcyonlab.app');
export const API_SECRET = import.meta.env.VITE_API_SECRET || '';
