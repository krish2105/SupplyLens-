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
        // A capacity refusal (503 overloaded, 429 workspace busy) did no work, so reads retry after the server's Retry-After;
        // other client errors are final; anything else gets two quick retries.
        retry: (count, err) => err instanceof ApiError && err.busy ? count < 3
          : !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
        retryDelay: (count, err) => err instanceof ApiError && err.retryAfter
          ? Math.min(err.retryAfter, 10) * 1000 : Math.min(1000 * 2 ** count, 8000),
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
