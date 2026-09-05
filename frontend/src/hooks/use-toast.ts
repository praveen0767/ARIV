"use client";

import { toast as toastManager } from "@/components/ui/toast";

interface ToastOptions {
  title?: string;
  description?: string;
  variant?: "default" | "destructive";
}

export function useToast() {
  const toast = (options: ToastOptions) => {
    const mgr = toastManager as any;
    if (typeof mgr.add === "function") {
      mgr.add({
        title: options.title,
        description: options.description,
        type: options.variant === "destructive" ? "error" : "info",
      });
    } else if (typeof mgr.create === "function") {
      mgr.create({
        title: options.title,
        description: options.description,
        type: options.variant === "destructive" ? "error" : "info",
      });
    }
  };

  return { toast };
}
