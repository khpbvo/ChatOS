/** WebSocket connection hook with auto-reconnect. */

import { useCallback, useEffect, useRef } from "react";
import type { ServerEvent } from "../types/events";
import type { ChatAction } from "../state/reducer";

const RECONNECT_BASE_MS = 3000;
const RECONNECT_CAP_MS = 30000;
const MAX_ATTEMPTS = 10;

function mapEventToAction(event: ServerEvent): ChatAction | null {
  switch (event.type) {
    case "thinking":
      return { type: "THINKING", text: event.text, timestamp: event.timestamp };
    case "tool_call":
      return {
        type: "TOOL_CALL",
        toolName: event.tool_name,
        toolInput: event.tool_input,
        timestamp: event.timestamp,
      };
    case "tool_output":
      return {
        type: "TOOL_OUTPUT",
        toolName: event.tool_name,
        output: event.output,
        truncated: event.truncated,
        timestamp: event.timestamp,
      };
    case "tool_collapse":
      return { type: "TOOL_COLLAPSE", toolName: event.tool_name };
    case "text":
      return { type: "TEXT", text: event.text, timestamp: event.timestamp };
    case "media":
      return {
        type: "MEDIA",
        mediaType: event.media_type,
        url: event.url,
        alt: event.alt,
        timestamp: event.timestamp,
      };
    case "ready":
      return { type: "READY", sessionToken: event.session_token };
    case "error":
      return {
        type: "SERVER_ERROR",
        error: event.error,
        code: event.code,
        timestamp: event.timestamp,
      };
  }
}

interface UseWebSocketOptions {
  url: string;
  dispatch: React.Dispatch<ChatAction>;
}

export function useWebSocket({ url, dispatch }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const connectRef = useRef<() => void>(null);

  const scheduleReconnect = useCallback(() => {
    if (attemptsRef.current >= MAX_ATTEMPTS) return;
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** attemptsRef.current,
      RECONNECT_CAP_MS,
    );
    attemptsRef.current += 1;
    timerRef.current = setTimeout(() => connectRef.current?.(), delay);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    dispatch({ type: "CONNECTING" });
    const ws = new WebSocket(url);

    ws.onopen = () => {
      attemptsRef.current = 0;
      dispatch({ type: "CONNECTED" });
    };

    ws.onmessage = (ev) => {
      try {
        const event: ServerEvent = JSON.parse(ev.data);
        const action = mapEventToAction(event);
        if (action) dispatch(action);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      dispatch({ type: "DISCONNECTED" });
      scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [url, dispatch, scheduleReconnect]);

  // Keep ref in sync so scheduleReconnect can call connect without circular dep
  connectRef.current = connect;

  const send = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", text }));
    }
  }, []);

  const reconnect = useCallback(() => {
    attemptsRef.current = 0;
    clearTimeout(timerRef.current);
    wsRef.current?.close();
    connect();
  }, [connect]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { send, reconnect };
}
