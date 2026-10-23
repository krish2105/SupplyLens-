import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useDraft } from "./draft";

beforeEach(() => window.sessionStorage.clear());

describe("unsent input (P2-FE-07)", () => {
  it("survives a remount and does not follow the user to another draft", () => {
    const { result, rerender, unmount } = renderHook(({ k }) => useDraft(k, ""), { initialProps: { k: "reject-reason:a" } });
    act(() => result.current[1]("wrong supplier"));
    rerender({ k: "reject-reason:b" });                 // another draft: starts empty, not with draft a's text
    expect(result.current[0]).toBe("");
    rerender({ k: "reject-reason:a" });
    expect(result.current[0]).toBe("wrong supplier");
    unmount();
    const again = renderHook(() => useDraft("reject-reason:a", ""));
    expect(again.result.current[0]).toBe("wrong supplier");
    act(() => again.result.current[2]());
    expect(window.sessionStorage.getItem("draft:reject-reason:a")).toBeNull();
  });
});
