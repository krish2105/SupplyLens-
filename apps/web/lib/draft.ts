"use client";
// Unsent user input (a rejection reason, edited quantities) survives a reload or a dropped connection.
// sessionStorage can be unavailable (private mode, blocked storage): the app then behaves as plain state.
import { useCallback, useEffect, useState } from "react";

export function useDraft<T>(key: string, initial: T): [T, (v: T) => void, () => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem("draft:" + key);
      if (raw != null) setValue(JSON.parse(raw) as T);
    } catch { /* storage unavailable */ }
  }, [key]);
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
