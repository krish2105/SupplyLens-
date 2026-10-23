"use client";
// Unsent user input (a rejection reason, edited quantities) survives a reload or a dropped connection.
// sessionStorage can be unavailable (private mode, blocked storage): the app then behaves as plain state.
import { useCallback, useEffect, useState } from "react";

export function useDraft<T>(key: string, initial: T): [T, (v: T) => void, () => void] {
  const [value, setValue] = useState<T>(initial);
  // Read after mount (storage does not exist during prerendering, so reading it while rendering would break hydration).
  // A key without a stored draft starts from `initial`: before, it kept the previous key's text, so a rejection reason
  // typed for one draft appeared under the next one (P2-FE-07).
  useEffect(() => {
    let stored: T = initial;
    try {
      const raw = window.sessionStorage.getItem("draft:" + key);
      if (raw != null) stored = JSON.parse(raw) as T;
    } catch { /* storage unavailable */ }
    setValue(stored); // eslint-disable-line react-hooks/set-state-in-effect -- browser storage is read once per key, after mount
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps -- `initial` is a default, not an input
  const set = useCallback((v: T) => {
    setValue(v);
    try { window.sessionStorage.setItem("draft:" + key, JSON.stringify(v)); } catch { /* ignore */ }
  }, [key]);
  const clear = useCallback(() => {
    setValue(initial);
    try { window.sessionStorage.removeItem("draft:" + key); } catch { /* ignore */ }
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return [value, set, clear];
}
