import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import App from "./App";
import "./index.css";

// With a key this is the real Clerk provider. Without one the build aliases
// "@clerk/clerk-react" to src/lib/auth-local.tsx, which ignores the prop.
const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ?? "";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");

createRoot(root).render(
  <ClerkProvider publishableKey={CLERK_KEY}>
    <App />
  </ClerkProvider>
);
