import type { ErrorItem } from "../state/reducer";
import "./ErrorMessage.css";

export function ErrorMessage({ item }: { item: ErrorItem }) {
  return (
    <div className="error-message">
      <span className="error-message__code">{item.code}</span>
      <span className="error-message__text">{item.error}</span>
    </div>
  );
}
