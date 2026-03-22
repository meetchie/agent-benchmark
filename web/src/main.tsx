import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import App from "./App";
import "./index.css";

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
if (!CLERK_KEY) throw new Error("Missing VITE_CLERK_PUBLISHABLE_KEY");

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");

createRoot(root).render(
  <ClerkProvider publishableKey={CLERK_KEY}>
    <App />
  </ClerkProvider>
);
