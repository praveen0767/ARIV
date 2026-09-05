"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { activityStore, ActivityEvent } from "@/components/ActivityToast";

interface ArivContextType {
  isOpen: boolean;
  openAriv: (query?: string) => void;
  closeAriv: () => void;
  toggleAriv: () => void;
  initialQuery: string | null;
  clearInitialQuery: () => void;
  proactiveEvent: ActivityEvent | null;
  dismissProactiveEvent: () => void;
}

const ArivContext = createContext<ArivContextType | undefined>(undefined);

export function ArivProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [initialQuery, setInitialQuery] = useState<string | null>(null);
  const [proactiveEvent, setProactiveEvent] = useState<ActivityEvent | null>(null);

  const openAriv = useCallback((query?: string) => {
    if (query) {
      setInitialQuery(query);
    }
    setIsOpen(true);
    setProactiveEvent(null);
  }, []);

  const closeAriv = useCallback(() => {
    setIsOpen(false);
  }, []);

  const toggleAriv = useCallback(() => {
    setIsOpen((prev) => !prev);
    setProactiveEvent(null);
  }, []);

  const clearInitialQuery = useCallback(() => {
    setInitialQuery(null);
  }, []);

  const dismissProactiveEvent = useCallback(() => {
    setProactiveEvent(null);
  }, []);

  // Keyboard shortcut: Ctrl+Shift+A or Cmd+Shift+A
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && (e.key === "A" || e.key === "a")) {
        e.preventDefault();
        toggleAriv();
      }
    };

    const handleArivToggle = () => toggleAriv();
    const handleArivOpen = (e: Event) => {
      const customEvent = e as CustomEvent<{ query?: string }>;
      openAriv(customEvent.detail?.query);
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("ask-ariv-toggle", handleArivToggle);
    window.addEventListener("ask-ariv-open", handleArivOpen);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("ask-ariv-toggle", handleArivToggle);
      window.removeEventListener("ask-ariv-open", handleArivOpen);
    };
  }, [toggleAriv, openAriv]);

  // Proactive notification on high-priority live events
  useEffect(() => {
    const unsub = activityStore.subscribe((events) => {
      if (events.length > 0) {
        const latest = events[0];
        // If drawer is closed and event is significant, show proactive banner
        setIsOpen((open) => {
          if (!open) {
            setProactiveEvent(latest);
          }
          return open;
        });
      }
    });
    return unsub;
  }, []);

  // Auto-dismiss proactive banner after 12s
  useEffect(() => {
    if (!proactiveEvent) return;
    const timer = setTimeout(() => {
      setProactiveEvent(null);
    }, 12000);
    return () => clearTimeout(timer);
  }, [proactiveEvent]);

  return (
    <ArivContext.Provider
      value={{
        isOpen,
        openAriv,
        closeAriv,
        toggleAriv,
        initialQuery,
        clearInitialQuery,
        proactiveEvent,
        dismissProactiveEvent,
      }}
    >
      {children}
    </ArivContext.Provider>
  );
}

export function useAriv(): ArivContextType {
  const context = useContext(ArivContext);
  if (!context) {
    throw new Error("useAriv must be used within an ArivProvider");
  }
  return context;
}
