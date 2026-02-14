"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { WebSocketProvider } from "@/context/WebSocketContext";
import { AssemblyProvider } from "@/context/AssemblyContext";
import { ExecutionProvider } from "@/context/ExecutionContext";
import { TeachingProvider } from "@/context/TeachingContext";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ revalidateOnFocus: false, shouldRetryOnError: false, dedupingInterval: 5000 }}>
      <WebSocketProvider>
        <AssemblyProvider>
          <ExecutionProvider>
            <TeachingProvider>{children}</TeachingProvider>
          </ExecutionProvider>
        </AssemblyProvider>
      </WebSocketProvider>
    </SWRConfig>
  );
}
