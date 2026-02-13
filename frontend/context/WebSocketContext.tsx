"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AuraWebSocket, type ConnectionState } from "@/lib/ws";

interface WebSocketContextValue {
  connected: boolean;
  connectionState: ConnectionState;
  lastMessage: unknown;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/execution/ws";

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [lastMessage, setLastMessage] = useState<unknown>(null);
  const wsRef = useRef<AuraWebSocket | null>(null);

  useEffect(() => {
    const ws = new AuraWebSocket(WS_URL);
    wsRef.current = ws;

    const unsubscribe = ws.onMessage((data) => {
      setLastMessage(data);
      setConnected(ws.connected);
      setConnectionState(ws.state);
    });

    ws.connect();
    // Poll connection state for reconnection transitions
    const pollId = setInterval(() => {
      setConnected(ws.connected);
      setConnectionState(ws.state);
    }, 1000);

    return () => {
      unsubscribe();
      clearInterval(pollId);
      ws.disconnect();
    };
  }, []);

  const value = useMemo<WebSocketContextValue>(
    () => ({ connected, connectionState, lastMessage }),
    [connected, connectionState, lastMessage],
  );

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error("useWebSocket must be used within WebSocketProvider");
  return ctx;
}
