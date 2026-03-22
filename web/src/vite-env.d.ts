/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CLERK_PUBLISHABLE_KEY: string;
}

declare module "*.yaml" {
  const data: {
    categories: Array<{
      id: string;
      label: string;
      tasks: Array<{ id: string; label: string; goal: string }>;
    }>;
  };
  export default data;
}
