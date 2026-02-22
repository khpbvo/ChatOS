import type { ChatItem } from "../state/reducer";
import { useAutoScroll } from "../hooks/useAutoScroll";
import { UserMessage } from "./UserMessage";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { ToolCallMessage } from "./ToolCallMessage";
import { TextMessage } from "./TextMessage";
import { MediaMessage } from "./MediaMessage";
import { ErrorMessage } from "./ErrorMessage";
import "./MessageList.css";

interface Props {
  items: ChatItem[];
  sessionToken: string;
}

export function MessageList({ items, sessionToken }: Props) {
  const { containerRef, handleScroll } = useAutoScroll(items);

  function renderItem(item: ChatItem) {
    switch (item.kind) {
      case "user":
        return <UserMessage key={item.id} item={item} />;
      case "thinking":
        return <ThinkingIndicator key={item.id} />;
      case "tool":
        return <ToolCallMessage key={item.id} item={item} />;
      case "text":
        return <TextMessage key={item.id} item={item} />;
      case "media":
        return <MediaMessage key={item.id} item={item} sessionToken={sessionToken} />;
      case "error":
        return <ErrorMessage key={item.id} item={item} />;
    }
  }

  return (
    <div className="message-list" ref={containerRef} onScroll={handleScroll}>
      {items.length === 0 && (
        <div className="message-list__empty">
          Welcome to ChatOS. Type a message to get started.
        </div>
      )}
      {items.map(renderItem)}
    </div>
  );
}
