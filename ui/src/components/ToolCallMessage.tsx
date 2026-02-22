import { useState } from "react";
import type { ToolItem } from "../state/reducer";
import "./ToolCallMessage.css";

function formatToolInput(toolInput: Record<string, unknown>): string {
  if ("command" in toolInput) return String(toolInput.command);
  if ("file_path" in toolInput) return String(toolInput.file_path);
  return JSON.stringify(toolInput);
}

export function ToolCallMessage({ item }: { item: ToolItem }) {
  const [manualExpand, setManualExpand] = useState(false);
  const isCollapsed = item.collapsed && !manualExpand;
  const inputSummary = formatToolInput(item.toolInput);

  return (
    <div className={`tool-call ${isCollapsed ? "tool-call--collapsed" : ""}`}>
      <button
        className="tool-call__header"
        onClick={() => setManualExpand(!manualExpand)}
        type="button"
      >
        <span className="tool-call__chevron">{isCollapsed ? "\u25b6" : "\u25bc"}</span>
        <span className="tool-call__name">{item.toolName}</span>
        {isCollapsed && (
          <span className="tool-call__summary">{inputSummary}</span>
        )}
      </button>

      {!isCollapsed && (
        <div className="tool-call__body">
          <pre className="tool-call__input">{inputSummary}</pre>
          {item.output !== null && (
            <pre className="tool-call__output">
              {item.output}
              {item.truncated && (
                <span className="tool-call__truncated"> (truncated)</span>
              )}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
