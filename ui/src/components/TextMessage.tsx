import type { TextItem } from "../state/reducer";
import "./TextMessage.css";

export function TextMessage({ item }: { item: TextItem }) {
  return (
    <div className="text-message">
      <div className="text-message__content">{item.text}</div>
    </div>
  );
}
