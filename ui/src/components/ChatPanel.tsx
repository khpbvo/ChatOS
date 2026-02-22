import type { ChatItem, ConnectionStatus as Status } from "../state/reducer";
import { ConnectionStatus } from "./ConnectionStatus";
import { MessageList } from "./MessageList";
import { InputBar } from "./InputBar";
import "./ChatPanel.css";

interface Props {
  items: ChatItem[];
  connectionStatus: Status;
  isAgentBusy: boolean;
  sessionToken: string;
  onSend: (text: string) => void;
  onReconnect: () => void;
}

export function ChatPanel({
  items,
  connectionStatus,
  isAgentBusy,
  sessionToken,
  onSend,
  onReconnect,
}: Props) {
  const inputDisabled = isAgentBusy || connectionStatus !== "connected";

  return (
    <div className="chat-panel">
      <ConnectionStatus status={connectionStatus} onReconnect={onReconnect} />
      <MessageList items={items} sessionToken={sessionToken} />
      <InputBar onSend={onSend} disabled={inputDisabled} />
    </div>
  );
}
