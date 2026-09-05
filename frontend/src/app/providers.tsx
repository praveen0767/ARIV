"use client";

import { useState, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CommandPalette } from "@/components/CommandPalette";
import { AskArivPanel } from "@/components/AskArivPanel";
import { AskArivLauncher } from "@/components/AskArivLauncher";
import { ActivityToastContainer } from "@/components/ActivityToast";
import { ArivProvider } from "@/context/ArivContext";

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        // Data is considered stale after 2s so refetchInterval will always refetch
        staleTime: 2_000,
        // Refetch when the user switches back to this tab
        refetchOnWindowFocus: true,
        // Keep previous data while fetching fresh — avoids flash of loading state
        placeholderData: (prev: unknown) => prev,
        // Retry failed requests up to 3 times with exponential backoff
        retry: 3,
        retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 10_000),
      },
    },
  }));

  const [cmdOpen, setCmdOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ArivProvider>
        {children}
        <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} />
        <AskArivPanel />
        <AskArivLauncher />
        <ActivityToastContainer />
      </ArivProvider>
    </QueryClientProvider>
  );
}
