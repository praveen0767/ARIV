"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { LayoutDashboard, FileStack, TrendingUp, PlaySquare, Settings, Activity, Bot } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { name: "Overview", href: "/", icon: LayoutDashboard },
  { name: "Cases", href: "/cases", icon: FileStack },
  { name: "Impact", href: "/impact", icon: TrendingUp },
  { name: "System Health", href: "/system", icon: Activity },
  { name: "Settings", href: "/settings", icon: Settings },
  { name: "Demo Simulator", href: "/demo", icon: PlaySquare },
];

export default function NavMenu() {
  const pathname = usePathname();

  return (
    <div className="w-64 border-r border-slate-200 bg-white flex flex-col hidden md:flex shadow-sm z-10">
      <div className="h-16 flex items-center px-6 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <Image src="/logo.png" alt="ARIV Logo" width={28} height={28} className="object-contain" />
          <span className="font-bold text-lg tracking-tight text-slate-900">
            ARIV <span className="text-slate-500 font-normal">Control</span>
          </span>
        </div>
      </div>
      <nav className="flex-1 py-6 px-4 space-y-1">
        <div className="mb-4 px-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
          Workspace
        </div>
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
              )}
            >
              <item.icon className={cn("w-4 h-4", isActive ? "text-blue-600" : "text-slate-400")} />
              {item.name}
            </Link>
          );
        })}
      </nav>
      <div className="p-4 border-t border-slate-200 bg-slate-50 space-y-2">
        {/* Ask ARIV panel trigger */}
        <button
          type="button"
          onClick={() => {
            if (typeof window !== "undefined") {
              window.dispatchEvent(new CustomEvent("ask-ariv-toggle"));
            }
          }}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium text-blue-700 bg-blue-50/70 hover:bg-blue-100/70 hover:text-blue-800 transition-colors border border-blue-200 shadow-2xs"
        >
          <Bot className="w-4 h-4 text-blue-600" />
          <span className="font-semibold">Ask ARIV</span>
        </button>
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>Command Palette</span>
          <kbd className="font-mono bg-slate-200 px-1.5 py-0.5 rounded text-slate-600 border border-slate-300 shadow-sm">Ctrl+K</kbd>
        </div>
      </div>
    </div>
  );
}
