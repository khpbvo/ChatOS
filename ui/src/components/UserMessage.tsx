import type { UserMessage as UserMessageItem } from "../state/reducer";
import "./UserMessage.css";

export function UserMessage({ item }: { item: UserMessageItem }) {
  return (
    <div className="user-message">
      <div className="user-message__bubble">{item.text}</div>
    </div>
  );
}
