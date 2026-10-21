"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      },
    },
  }));
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem storageKey="supplylens-theme" disableTransitionOnChange>
      <NuqsAdapter>
        <QueryClientProvider client={client}>
          <Tooltip.Provider delayDuration={250}>{children}</Tooltip.Provider>
        </QueryClientProvider>
      </NuqsAdapter>
    </ThemeProvider>
  );
}
