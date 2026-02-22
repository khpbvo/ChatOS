/** TypeScript mirrors of Python Event models from src/models.py.
 *  Field names use snake_case to match the JSON wire format. */

export interface ThinkingEvent {
  type: "thinking";
  text: string;
  timestamp: string;
}

export interface ToolCallEvent {
  type: "tool_call";
  tool_name: string;
  tool_input: Record<string, unknown>;
  timestamp: string;
}

export interface ToolOutputEvent {
  type: "tool_output";
  tool_name: string;
  output: string;
  truncated: boolean;
  timestamp: string;
}

export interface ToolCollapseEvent {
  type: "tool_collapse";
  tool_name: string;
  timestamp: string;
}

export interface TextEvent {
  type: "text";
  text: string;
  timestamp: string;
}

export interface MediaEvent {
  type: "media";
  media_type: "image" | "video" | "link";
  url: string;
  alt: string;
  timestamp: string;
}

export interface ReadyEvent {
  type: "ready";
  timestamp: string;
}

export interface ErrorEvent {
  type: "error";
  error: string;
  code: string;
  timestamp: string;
}

export type ServerEvent =
  | ThinkingEvent
  | ToolCallEvent
  | ToolOutputEvent
  | ToolCollapseEvent
  | TextEvent
  | MediaEvent
  | ReadyEvent
  | ErrorEvent;

export interface ClientMessage {
  type: "message";
  text: string;
}
