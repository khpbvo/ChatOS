import { useRef, useState } from "react";
import "./InputBar.css";

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
}

export function InputBar({ onSend, disabled }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="input-bar">
      <input
        ref={inputRef}
        className="input-bar__input"
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? "Waiting for response..." : "Type a message..."}
        disabled={disabled}
        autoFocus
      />
      <button
        className="input-bar__send"
        onClick={handleSubmit}
        disabled={disabled || !text.trim()}
        type="button"
      >
        Send
      </button>
    </div>
  );
}
