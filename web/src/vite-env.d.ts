/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BASEMAP?: string;
  readonly VITE_API_PROXY?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
