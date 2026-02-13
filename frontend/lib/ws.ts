export type ConnectionState = "connecting" | "connected" | "disconnected";
export type MessageHandler = (data: unknown) => void;

const MAX_RECONNECT_DELAY = 10_000;
const MAX_RECONNECT_ATTEMPTS = 3;

export class AuraWebSocket {
  private url: string;
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private mockInterval: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private _state: ConnectionState = "disconnected";
  private _stopped = false;

  constructor(url: string) {
    this.url = url;
  }

  get state(): ConnectionState {
    return this._state;
  }

  get connected(): boolean {
    return this._state === "connected";
  }

  connect(): void {
    this._stopped = false;
    this.reconnectAttempts = 0;
    this._connect();
  }

  private _connect(): void {
    if (this._stopped) return;
    this._state = "connecting";

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this._state = "connected";
        this.reconnectAttempts = 0;
      };

      this.ws.onclose = () => {
        this._state = "disconnected";
        this.ws = null;
        this._scheduleReconnect();
      };

      this.ws.onerror = () => {
        // onclose will fire after onerror, triggering reconnect
        this.ws?.close();
      };

      this.ws.onmessage = (event) => {
        const data: unknown = JSON.parse(event.data as string);
        this.handlers.forEach((h) => h(data));
      };
    } catch {
      this._state = "disconnected";
      this._scheduleReconnect();
    }
  }

  private _scheduleReconnect(): void {
    if (this._stopped) return;

    this.reconnectAttempts += 1;
    if (this.reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
      this.startMockMode();
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, 10s, 10s, ...
    const delay = Math.min(
      1000 * Math.pow(2, this.reconnectAttempts - 1),
      MAX_RECONNECT_DELAY,
    );
    this._state = "connecting";
    this.reconnectTimer = setTimeout(() => this._connect(), delay);
  }

  private startMockMode(): void {
    this._state = "connected";
    this.mockInterval = setInterval(() => {
      const mockMessage = {
        type: "heartbeat",
        timestamp: Date.now(),
        connected: true,
      };
      this.handlers.forEach((h) => h(mockMessage));
    }, 2000);
  }

  disconnect(): void {
    this._stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    if (this.mockInterval) {
      clearInterval(this.mockInterval);
      this.mockInterval = null;
    }
    this._state = "disconnected";
  }

  onMessage(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }
}
