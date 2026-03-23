import { useState } from "react";
import { useSignIn, useSignUp } from "@clerk/clerk-react";

type AuthView = "signin" | "signup";

interface SignInModalProps {
  onClose?: () => void;
}

export function SignInModal({ onClose }: SignInModalProps) {
  const [authView, setAuthView] = useState<AuthView>("signin");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#3c49ad]/15 backdrop-blur-sm">
      <div className="w-full max-w-[420px] mx-4">
        <div className="bg-white border-2 border-slate-200 p-6 relative">
          {/* Logo + heading inside card */}
          <div className="text-center mb-6">
            <div className="flex items-center justify-center gap-2.5 mb-3">
              <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto" />
              <span className="text-lg font-semibold text-slate-900">Rindler</span>
            </div>
            <h1 className="text-xl font-bold text-slate-900">
              {authView === "signin" ? "Welcome back" : "Create your account"}
            </h1>
            {authView === "signup" && (
              <p className="text-sm text-slate-500 mt-1">Enter your details to get started.</p>
            )}
          </div>

          {authView === "signin" ? (
            <SignInForm />
          ) : (
            <SignUpForm />
          )}

          <p className="text-center text-sm text-slate-500 mt-5">
            {authView === "signin" ? (
              <>
                Don't have an account?{" "}
                <button onClick={() => setAuthView("signup")} className="text-[#3c49ad] font-semibold hover:underline">
                  Sign up
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button onClick={() => setAuthView("signin")} className="text-[#3c49ad] font-semibold hover:underline">
                  Sign in
                </button>
              </>
            )}
          </p>

          {onClose && (
            <button
              onClick={onClose}
              className="absolute top-3 right-3 text-slate-400 hover:text-slate-600"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SignInForm() {
  const { signIn, isLoaded, setActive } = useSignIn();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleEmailPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;
    setError(null);
    setLoading(true);

    try {
      const result = await signIn.create({
        identifier: email,
        password,
      });

      if (result.status === "complete" && result.createdSessionId) {
        await setActive({ session: result.createdSessionId });
      } else {
        setError("Sign in incomplete. Please try again.");
      }
    } catch (err: any) {
      const msg = err?.errors?.[0]?.longMessage || err?.errors?.[0]?.message || "Sign in failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleGoogle = async () => {
    if (!isLoaded) return;
    try {
      await signIn.authenticateWithRedirect({
        strategy: "oauth_google",
        redirectUrl: "/sso-callback",
        redirectUrlComplete: "/",
      });
    } catch {
      setError("Google sign in failed. Please try again.");
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <div className="border-2 border-red-300 bg-red-50 px-4 py-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <button
        type="button"
        onClick={handleGoogle}
        className="w-full border-2 border-slate-300 bg-white py-2.5 text-sm font-medium text-slate-700 flex items-center justify-center gap-2 hover:border-[#3c49ad] hover:text-[#3c49ad] transition-colors"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>
        Continue with Google
      </button>

      <div className="flex items-center gap-3">
        <div className="flex-1 border-t border-slate-200" />
        <span className="text-xs text-slate-400 uppercase">or</span>
        <div className="flex-1 border-t border-slate-200" />
      </div>

      <form onSubmit={handleEmailPassword} className="space-y-4">
        <div className="space-y-1">
          <label className="text-sm font-semibold text-slate-700">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Enter your email"
            required
            className="w-full border-2 border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-[#3c49ad] bg-white text-slate-900"
          />
        </div>

        <div className="space-y-1">
          <label className="text-sm font-semibold text-slate-700">Password</label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              required
              className="w-full border-2 border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-[#3c49ad] bg-white text-slate-900 pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              <EyeIcon show={showPassword} />
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full mt-5 border-2 border-[#3c49ad] bg-[#3c49ad] text-white py-2.5 text-sm font-semibold hover:bg-[#2f3a8a] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}

function SignUpForm() {
  const { signUp, isLoaded, setActive } = useSignUp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLoaded) return;
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      const result = await signUp.create({
        emailAddress: email,
        password,
      });

      if (result.status === "complete" && result.createdSessionId) {
        await setActive({ session: result.createdSessionId });
      } else {
        setError("Please check your email to verify your account.");
      }
    } catch (err: any) {
      const msg = err?.errors?.[0]?.longMessage || err?.errors?.[0]?.message || "Sign up failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {error && (
        <div className="border-2 border-red-300 bg-red-50 px-4 py-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      <div className="space-y-1">
        <label className="text-sm font-semibold text-slate-700">Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Enter your email"
          required
          className="w-full border-2 border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-[#3c49ad] bg-white text-slate-900"
        />
      </div>

      <div className="space-y-1">
        <label className="text-sm font-semibold text-slate-700">Password</label>
        <div className="relative">
          <input
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Create a password"
            required
            className="w-full border-2 border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-[#3c49ad] bg-white text-slate-900 pr-10"
          />
          <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
            <EyeIcon show={showPassword} />
          </button>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-sm font-semibold text-slate-700">Confirm Password</label>
        <div className="relative">
          <input
            type={showConfirm ? "text" : "password"}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Confirm your password"
            required
            className="w-full border-2 border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-[#3c49ad] bg-white text-slate-900 pr-10"
          />
          <button type="button" onClick={() => setShowConfirm(!showConfirm)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
            <EyeIcon show={showConfirm} />
          </button>
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full mt-5 border-2 border-[#3c49ad] bg-[#3c49ad] text-white py-2.5 text-sm font-semibold hover:bg-[#2f3a8a] disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? "Creating account..." : "Sign up"}
      </button>
    </form>
  );
}

function EyeIcon({ show }: { show: boolean }) {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      {show ? (
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
      ) : (
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178zM15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      )}
    </svg>
  );
}
