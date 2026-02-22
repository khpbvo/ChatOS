/** Auto-scroll hook: scrolls to bottom when items change,
 *  unless the user has scrolled up. */

import { useCallback, useEffect, useRef } from "react";

const SCROLL_THRESHOLD = 100;

export function useAutoScroll<T>(deps: T[]) {
  const containerRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    userScrolledUp.current = distanceFromBottom > SCROLL_THRESHOLD;
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || userScrolledUp.current) return;
    el.scrollTop = el.scrollHeight;
  }, [deps]);

  return { containerRef, handleScroll };
}
