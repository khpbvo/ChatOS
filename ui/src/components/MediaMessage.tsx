import type { MediaItem } from "../state/reducer";
import "./MediaMessage.css";

interface Props {
  item: MediaItem;
  sessionToken: string;
}

function resolveUrl(url: string, sessionToken: string): string {
  if (url.startsWith("/files/") && sessionToken) {
    return `${url}?token=${encodeURIComponent(sessionToken)}`;
  }
  return url;
}

export function MediaMessage({ item, sessionToken }: Props) {
  const url = resolveUrl(item.url, sessionToken);

  switch (item.mediaType) {
    case "image":
      return (
        <div className="media-message">
          <img className="media-message__image" src={url} alt={item.alt} />
        </div>
      );
    case "video":
      return (
        <div className="media-message">
          <video className="media-message__video" src={url} controls>
            {item.alt}
          </video>
        </div>
      );
    case "link":
      return (
        <div className="media-message">
          <a
            className="media-message__link"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {item.alt || item.url}
          </a>
        </div>
      );
  }
}
