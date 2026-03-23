import { createRoot } from "react-dom/client";
import { ClerkProvider } from "@clerk/clerk-react";
import App from "./App";
import "./index.css";

const CLERK_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
if (!CLERK_KEY) throw new Error("Missing VITE_CLERK_PUBLISHABLE_KEY");

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");

const clerkAppearance = {
  variables: {
    colorPrimary: "#3c49ad",
    colorText: "#1e293b",
    colorTextSecondary: "#64748b",
    colorBackground: "#ffffff",
    colorInputBackground: "#ffffff",
    colorInputText: "#1e293b",
    borderRadius: "0px",
    fontFamily: "inherit",
  },
  elements: {
    card: "shadow-none border-2 border-slate-200",
    headerTitle: "text-2xl font-bold text-slate-900",
    headerSubtitle: "text-sm text-slate-500",
    formButtonPrimary:
      "bg-[#3c49ad] border-2 border-[#3c49ad] hover:bg-[#2f3a8a] text-white font-semibold rounded-none",
    formFieldInput:
      "border-2 border-slate-300 rounded-none focus:border-[#3c49ad] outline-none",
    formFieldLabel: "text-sm font-semibold text-slate-700",
    socialButtonsBlockButton:
      "border-2 border-slate-300 rounded-none hover:border-[#3c49ad] font-medium",
    footerActionLink: "text-[#3c49ad] font-semibold hover:text-[#2f3a8a]",
    dividerLine: "bg-slate-200",
    dividerText: "text-xs text-slate-400 uppercase",
    identityPreview: "border-2 border-slate-200 rounded-none",
    formResendCodeLink: "text-[#3c49ad]",
    logoBox: "hidden",
  },
};

createRoot(root).render(
  <ClerkProvider publishableKey={CLERK_KEY} appearance={clerkAppearance}>
    <App />
  </ClerkProvider>
);
