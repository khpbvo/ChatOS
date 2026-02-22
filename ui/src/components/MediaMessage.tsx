import type { MediaItem } from "../state/reducer";
import "./MediaMessage.css";

export function MediaMessage({ item }: { item: MediaItem }) {
  switch (item.mediaType) {
    case "image":
      return (
        <div className="media-message">
          <img className="media-message__image" src={item.url} alt={item.alt} />
        </div>
      );
    case "video":
      return (
        <div className="media-message">
          <video className="media-message__video" src={item.url} controls>
            {item.alt}
          </video>
        </div>
      );
    case "link":
      return (
        <div className="media-message">
          <a
            className="media-message__link"
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {item.alt || item.url}
          </a>
        </div>
      );
  }
}
