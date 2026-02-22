import { useCallback, useReducer } from "react";
import { chatReducer, initialState } from "./state/reducer";
import { useWebSocket } from "./hooks/useWebSocket";
import { ChatPanel } from "./components/ChatPanel";

const WS_URL = `ws://${location.host}/ws`;

export function App() {
  const [state, dispatch] = useReducer(chatReducer, initialState);
  const { send, reconnect } = useWebSocket({ url: WS_URL, dispatch });

  const handleSend = useCallback(
    (text: string) => {
      dispatch({ type: "USER_MESSAGE", text });
      send(text);
    },
    [send],
  );

  return (
    <ChatPanel
      items={state.items}
      connectionStatus={state.connectionStatus}
      isAgentBusy={state.isAgentBusy}
      sessionToken={state.sessionToken}
      onSend={handleSend}
      onReconnect={reconnect}
    />
  );
}
