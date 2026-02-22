/** Chat state management via useReducer. */

// -- Chat item types --

interface BaseItem {
  id: string;
  timestamp: string;
}

export interface UserMessage extends BaseItem {
  kind: "user";
  text: string;
}

export interface ThinkingItem extends BaseItem {
  kind: "thinking";
  text: string;
}

export interface ToolItem extends BaseItem {
  kind: "tool";
  toolName: string;
  toolInput: Record<string, unknown>;
  output: string | null;
  truncated: boolean;
  collapsed: boolean;
}

export interface TextItem extends BaseItem {
  kind: "text";
  text: string;
}

export interface MediaItem extends BaseItem {
  kind: "media";
  mediaType: "image" | "video" | "link";
  url: string;
  alt: string;
}

export interface ErrorItem extends BaseItem {
  kind: "error";
  error: string;
  code: string;
}

export type ChatItem =
  | UserMessage
  | ThinkingItem
  | ToolItem
  | TextItem
  | MediaItem
  | ErrorItem;

// -- Connection status --

export type ConnectionStatus = "connected" | "connecting" | "disconnected";

// -- State --

export interface ChatState {
  items: ChatItem[];
  connectionStatus: ConnectionStatus;
  isAgentBusy: boolean;
  sessionToken: string;
  nextId: number;
}

export const initialState: ChatState = {
  items: [],
  connectionStatus: "disconnected",
  isAgentBusy: false,
  sessionToken: "",
  nextId: 1,
};

// -- Actions --

export type ChatAction =
  | { type: "CONNECTED" }
  | { type: "CONNECTING" }
  | { type: "READY"; sessionToken: string }
  | { type: "DISCONNECTED" }
  | { type: "USER_MESSAGE"; text: string }
  | { type: "THINKING"; text: string; timestamp: string }
  | { type: "TOOL_CALL"; toolName: string; toolInput: Record<string, unknown>; timestamp: string }
  | { type: "TOOL_OUTPUT"; toolName: string; output: string; truncated: boolean; timestamp: string }
  | { type: "TOOL_COLLAPSE"; toolName: string }
  | { type: "TEXT"; text: string; timestamp: string }
  | { type: "MEDIA"; mediaType: "image" | "video" | "link"; url: string; alt: string; timestamp: string }
  | { type: "SERVER_ERROR"; error: string; code: string; timestamp: string };

// -- Helpers --

function removeThinking(items: ChatItem[]): ChatItem[] {
  return items.filter((item) => item.kind !== "thinking");
}

function findLastToolIndex(items: ChatItem[], toolName: string): number {
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].kind === "tool" && (items[i] as ToolItem).toolName === toolName) {
      return i;
    }
  }
  return -1;
}

function updateToolItem(items: ChatItem[], toolName: string, updater: (t: ToolItem) => ToolItem): ChatItem[] {
  const idx = findLastToolIndex(items, toolName);
  if (idx === -1) return items;
  const updated = [...items];
  updated[idx] = updater(items[idx] as ToolItem);
  return updated;
}

// -- Reducer --

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "CONNECTED":
      return { ...state, connectionStatus: "connected" };

    case "READY":
      return { ...state, connectionStatus: "connected", sessionToken: action.sessionToken };

    case "CONNECTING":
      return { ...state, connectionStatus: "connecting" };

    case "DISCONNECTED":
      return { ...state, connectionStatus: "disconnected", isAgentBusy: false };

    case "USER_MESSAGE": {
      const id = String(state.nextId);
      const item: UserMessage = {
        id,
        kind: "user",
        text: action.text,
        timestamp: new Date().toISOString(),
      };
      return {
        ...state,
        items: [...state.items, item],
        isAgentBusy: true,
        nextId: state.nextId + 1,
      };
    }

    case "THINKING": {
      const id = String(state.nextId);
      const item: ThinkingItem = {
        id,
        kind: "thinking",
        text: action.text,
        timestamp: action.timestamp,
      };
      return {
        ...state,
        items: [...removeThinking(state.items), item],
        nextId: state.nextId + 1,
      };
    }

    case "TOOL_CALL": {
      const id = String(state.nextId);
      const item: ToolItem = {
        id,
        kind: "tool",
        toolName: action.toolName,
        toolInput: action.toolInput,
        output: null,
        truncated: false,
        collapsed: false,
        timestamp: action.timestamp,
      };
      return {
        ...state,
        items: [...removeThinking(state.items), item],
        nextId: state.nextId + 1,
      };
    }

    case "TOOL_OUTPUT": {
      const items = updateToolItem(state.items, action.toolName, (t) => ({
        ...t,
        output: action.output,
        truncated: action.truncated,
      }));
      return { ...state, items };
    }

    case "TOOL_COLLAPSE": {
      const items = updateToolItem(state.items, action.toolName, (t) => ({
        ...t,
        collapsed: true,
      }));
      return { ...state, items };
    }

    case "TEXT": {
      const id = String(state.nextId);
      const item: TextItem = {
        id,
        kind: "text",
        text: action.text,
        timestamp: action.timestamp,
      };
      return {
        ...state,
        items: [...removeThinking(state.items), item],
        isAgentBusy: false,
        nextId: state.nextId + 1,
      };
    }

    case "MEDIA": {
      const id = String(state.nextId);
      const item: MediaItem = {
        id,
        kind: "media",
        mediaType: action.mediaType,
        url: action.url,
        alt: action.alt,
        timestamp: action.timestamp,
      };
      return {
        ...state,
        items: [...removeThinking(state.items), item],
        nextId: state.nextId + 1,
      };
    }

    case "SERVER_ERROR": {
      const id = String(state.nextId);
      const item: ErrorItem = {
        id,
        kind: "error",
        error: action.error,
        code: action.code,
        timestamp: action.timestamp,
      };
      return {
        ...state,
        items: [...removeThinking(state.items), item],
        isAgentBusy: false,
        nextId: state.nextId + 1,
      };
    }

    default:
      return state;
  }
}
