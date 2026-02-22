import type { ConnectionStatus as Status } from "../state/reducer";
import "./ConnectionStatus.css";

interface Props {
  status: Status;
  onReconnect: () => void;
}

export function ConnectionStatus({ status, onReconnect }: Props) {
  return (
    <div className="connection-status">
      <span className={`connection-status__dot connection-status__dot--${status}`} />
      <span className="connection-status__label">
        {status === "connected" && "Connected"}
        {status === "connecting" && "Connecting..."}
        {status === "disconnected" && "Disconnected"}
      </span>
      {status === "disconnected" && (
        <button
          className="connection-status__reconnect"
          onClick={onReconnect}
          type="button"
        >
          Reconnect
        </button>
      )}
    </div>
  );
}
