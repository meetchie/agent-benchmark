/// <reference types="vite/client" />

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
