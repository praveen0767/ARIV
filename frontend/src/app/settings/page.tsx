"use client";

import { ShieldCheck, Webhook, MessageSquare, Settings2, AlertTriangle, EyeOff } from "lucide-react";

function SettingSection({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="border border-slate-200 rounded-xl bg-white shadow-sm">
      <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-slate-200 bg-slate-50 rounded-t-xl">
        {icon}
        <span className="font-semibold text-sm text-slate-800">{title}</span>
      </div>
      <div className="p-5 space-y-4">{children}</div>
    </div>
  );
}

function SettingRow({ label, value, masked }: { label: string; value: string; masked?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
      <span className="text-sm text-slate-500">{label}</span>
      <div className="flex items-center gap-2">
        {masked && <EyeOff className="w-3.5 h-3.5 text-slate-400" />}
        <span className="text-sm font-semibold text-slate-800 font-mono">{masked ? "••••••••" : value}</span>
      </div>
    </div>
  );
}

function StatusPill({ label, active }: { label: string; active: boolean }) {
  return (
    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
      active
        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
        : "bg-slate-100 text-slate-500 border-slate-200"
    }`}>
      {label}
    </span>
  );
}

export default function SettingsPage() {
  const razorpayKeyId = process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID;
  const isDemoMode = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500 mt-1">
          Enterprise configuration for ARIV integrations and recovery policies.
        </p>
      </div>

      {/* Security Note */}
      <div className="flex items-start gap-3 p-4 bg-blue-50 border border-blue-200 rounded-xl text-sm text-blue-700">
        <ShieldCheck className="w-5 h-5 mt-0.5 flex-shrink-0 text-blue-600" />
        <div>
          <div className="font-semibold mb-0.5">Secrets are kept server-side</div>
          <div className="text-blue-600 text-xs">
            HMAC signing keys, Razorpay secret keys, Telegram bot tokens, and provider credentials are never
            exposed to the browser. All sensitive operations use Next.js server routes.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Razorpay */}
        <SettingSection title="Razorpay" icon={<Webhook className="w-4 h-4 text-blue-600" />}>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600 font-medium">Environment</span>
            <StatusPill label={isDemoMode ? "SANDBOX" : "TEST MODE"} active />
          </div>
          <SettingRow label="Key ID" value={razorpayKeyId ?? "Configured server-side"} />
          <SettingRow label="Secret Key" value="rzp_test_..." masked />
          <SettingRow label="Webhook Secret" value="whsec_..." masked />
          <div className="mt-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
            <div className="text-xs font-semibold text-amber-700 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              Test Mode Active
            </div>
            <div className="text-xs text-amber-600 mt-1">
              All Razorpay operations use test-mode credentials. No real money is moved.
            </div>
          </div>
        </SettingSection>

        {/* Telegram */}
        <SettingSection title="Telegram Notifications" icon={<MessageSquare className="w-4 h-4 text-blue-500" />}>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600 font-medium">Connector Status</span>
            <StatusPill label="Configured server-side" active={false} />
          </div>
          <SettingRow label="Bot Token" value="Set via TELEGRAM_BOT_TOKEN env" masked />
          <SettingRow label="Chat ID" value="Set via TELEGRAM_CHAT_ID env" masked />
          <div className="text-xs text-slate-400 mt-2">
            Telegram bot token and chat ID are stored as environment variables and never sent to the browser.
            Configure these in your backend <code className="bg-slate-100 px-1 py-0.5 rounded">.env</code> file.
          </div>
        </SettingSection>

        {/* Recovery Policies */}
        <SettingSection title="Recovery Policies" icon={<Settings2 className="w-4 h-4 text-purple-600" />}>
          <SettingRow label="Autonomy Level" value="SUPERVISED" />
          <SettingRow label="Max Retry Budget" value="3 attempts" />
          <SettingRow label="Cooldown Period" value="24 hours" />
          <SettingRow label="Approval Required" value="For high-risk actions" />
          <SettingRow label="Execution Kill Switch" value="Inactive" />
          <div className="text-xs text-slate-400 mt-2">
            Policy rules are managed by the deterministic Policy Engine in the backend.
            Changes require a backend deployment.
          </div>
        </SettingSection>

        {/* Deployment */}
        <SettingSection title="Deployment" icon={<ShieldCheck className="w-4 h-4 text-emerald-600" />}>
          <SettingRow label="Frontend" value="Next.js / Vercel-compatible" />
          <SettingRow label="Backend" value="FastAPI" />
          <SettingRow label="Database" value="PostgreSQL (Alembic migrations)" />
          <SettingRow label="Cache" value="Redis" />
          <SettingRow label="Vector Store" value="Qdrant" />
          <SettingRow label="Proxy" value="Server-side HMAC signing" />
          <div className="text-xs text-slate-400 mt-2">
            All backend credentials are proxied via Next.js server routes. The frontend never talks directly to external services.
          </div>
        </SettingSection>
      </div>
    </div>
  );
}
