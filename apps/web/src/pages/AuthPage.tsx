import { useState } from "react";
import { ArrowLeft, Braces, CheckCircle2, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { useMutation } from "@tanstack/react-query";

import { googleLoginUrl, login, resendVerification, signup } from "@/lib/api";
import type { AuthProviders, AuthUser } from "@/lib/schemas";

export function AuthPage({
  providers,
  oauthError,
  onAuthenticated,
  onBack,
}: {
  providers?: AuthProviders;
  oauthError?: string | null;
  onAuthenticated: (user: AuthUser) => void;
  onBack: () => void;
}) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [delivery, setDelivery] = useState<{ message: string; verification_url?: string | null } | null>(null);

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: onAuthenticated,
  });
  const signupMutation = useMutation({
    mutationFn: signup,
    onSuccess: (result) => setDelivery(result),
  });
  const resendMutation = useMutation({
    mutationFn: () => resendVerification(email),
    onSuccess: (result) => setDelivery(result),
  });
  const activeMutation = mode === "login" ? loginMutation : signupMutation;

  return (
    <main className="grid min-h-screen place-items-center bg-ink-950 px-5 py-10">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(49,87,213,.09),transparent_42%)]" />
      <section className="relative w-full max-w-md rounded-2xl border border-edge bg-ink-900/95 p-6 shadow-lg shadow-black/10 sm:p-8">
        <button type="button" onClick={onBack} className="flex items-center gap-2 text-xs text-fog hover:text-snow">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to showcase
        </button>
        <div className="mt-6 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent-deep text-white">
            <Braces className="h-5 w-5" />
          </div>
          <div>
            <h1 className="font-bold text-snow">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
            <p className="text-xs text-fog">Your research workspaces stay private to you.</p>
          </div>
        </div>

        {delivery ? (
          <div className="mt-7 rounded-xl border border-emerald-400/25 bg-emerald-400/5 p-5 text-center">
            <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-300" />
            <h2 className="mt-3 text-sm font-semibold text-snow">{delivery.verification_url ? "Local verification" : "Check your inbox"}</h2>
            <p className="mt-2 text-xs leading-5 text-fog">
              {delivery.message} {delivery.verification_url ? "A real email provider is required before production." : `It was accepted for delivery to ${email}.`}
            </p>
            {delivery.verification_url ? <a className="mt-4 block rounded-lg bg-accent-deep px-3 py-2 text-xs font-semibold text-white" href={delivery.verification_url}>Verify this development account</a> : null}
            {!delivery.verification_url ? <button disabled={resendMutation.isPending} className="mt-4 text-xs font-semibold text-indigo-300 disabled:opacity-50" onClick={() => resendMutation.mutate()}>{resendMutation.isPending ? "Sending…" : "Resend verification email"}</button> : null}
            {resendMutation.error ? <p className="mt-3 text-xs text-red-300">{resendMutation.error.message}</p> : null}
            <button className="mt-4 block w-full text-xs font-semibold text-indigo-300" onClick={() => { setDelivery(null); setMode("login"); }}>
              Return to sign in
            </button>
          </div>
        ) : (
          <>
            {oauthError ? (
              <p className="mt-6 rounded-lg border border-red-400/25 bg-red-400/5 px-3 py-2 text-xs text-red-300">
                Google sign-in could not be completed. Please try again or use email.
              </p>
            ) : null}
            {providers?.google ? (
              <a
                href={googleLoginUrl()}
                className={`${oauthError ? "mt-4" : "mt-7"} flex w-full items-center justify-center gap-3 rounded-lg border border-edge-2 bg-ink-800 px-4 py-2.5 text-sm font-semibold text-snow transition hover:border-indigo-400/50`}
              >
                <span className="grid h-5 w-5 place-items-center rounded-full bg-white text-xs font-bold text-blue-600">G</span>
                Continue with Google
              </a>
            ) : (
              <div className={`${oauthError ? "mt-4" : "mt-7"}`}>
                <button disabled className="flex w-full cursor-not-allowed items-center justify-center gap-3 rounded-lg border border-edge-2 bg-ink-800 px-4 py-2.5 text-sm font-semibold text-fog opacity-70">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-white text-xs font-bold text-blue-600">G</span>
                  {providers ? "Google sign-in not configured" : "Checking Google sign-in…"}
                </button>
                {providers ? <p className="mt-2 text-center text-[10px] text-amber-200">The deployment owner must set the Google OAuth client ID and secret.</p> : null}
              </div>
            )}

            <div className="my-5 flex items-center gap-3 text-[10px] uppercase tracking-widest text-fog"><span className="h-px flex-1 bg-edge" />or use email<span className="h-px flex-1 bg-edge" /></div>

            <form
              className=""
              onSubmit={(event) => {
                event.preventDefault();
                if (mode === "login") loginMutation.mutate({ email, password });
                else signupMutation.mutate({ email, password, display_name: displayName });
              }}
            >
              {mode === "signup" ? (
                <label className="block text-xs font-medium text-mist">
                  Name
                  <input required autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="mt-1.5 w-full rounded-lg border border-edge-2 bg-ink-800 px-3 py-2.5 text-sm text-snow outline-none focus:border-indigo-400/60" />
                </label>
              ) : null}
              <label className={`${mode === "signup" ? "mt-4" : ""} block text-xs font-medium text-mist`}>
                Email
                <div className="relative mt-1.5"><Mail className="absolute left-3 top-3 h-4 w-4 text-fog" /><input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className="w-full rounded-lg border border-edge-2 bg-ink-800 py-2.5 pl-10 pr-3 text-sm text-snow outline-none focus:border-indigo-400/60" /></div>
              </label>
              <label className="mt-4 block text-xs font-medium text-mist">
                Password
                <div className="relative mt-1.5"><LockKeyhole className="absolute left-3 top-3 h-4 w-4 text-fog" /><input required minLength={mode === "signup" ? 12 : 1} maxLength={128} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} className="w-full rounded-lg border border-edge-2 bg-ink-800 py-2.5 pl-10 pr-3 text-sm text-snow outline-none focus:border-indigo-400/60" /></div>
                {mode === "signup" ? <span className="mt-1.5 block text-[10px] text-fog">Use at least 12 characters. Passwords are stored with Argon2 hashing.</span> : null}
              </label>
              {activeMutation.error ? <p className="mt-4 rounded-lg border border-red-400/25 bg-red-400/5 px-3 py-2 text-xs text-red-300">{activeMutation.error.message}</p> : null}
              <button disabled={activeMutation.isPending} className="mt-5 w-full rounded-lg bg-accent-deep px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-50">
                {activeMutation.isPending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
              </button>
            </form>
            <p className="mt-5 text-center text-xs text-fog">
              {mode === "login" ? "New to CitePilot?" : "Already have an account?"}{" "}
              <button className="font-semibold text-indigo-300 hover:text-indigo-200" onClick={() => { setMode(mode === "login" ? "signup" : "login"); activeMutation.reset(); }}>
                {mode === "login" ? "Create an account" : "Sign in"}
              </button>
            </p>
          </>
        )}

        <div className="mt-6 flex items-center justify-center gap-2 border-t border-edge pt-5 text-[10px] text-fog">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" /> Secure, HttpOnly sessions · verified accounts
        </div>
      </section>
    </main>
  );
}
