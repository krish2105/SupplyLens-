import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { ErrorState, QueryError, TabList, TabPanel } from "./ui";

describe("error states (P2-FE-06)", () => {
  it("QueryError renders nothing without an error, and the error with a working retry otherwise", () => {
    const { container } = render(<QueryError q={{ error: null, refetch: () => {} }} what="members" />);
    expect(container.innerHTML).toBe("");
    const refetch = vi.fn();
    render(<QueryError q={{ error: new ApiError(500, "server_error", "The server hit an unexpected error.", undefined, "ref123456789xyz"), refetch }} what="members" />);
    expect(screen.getByText("Could not load members.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("ref ref123456789");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("denied, expired and offline read differently", () => {
    render(<ErrorState error={new ApiError(403, "forbidden", "no")} />);
    expect(screen.getByText("You do not have access to this")).toBeTruthy();
    render(<ErrorState error={new ApiError(401, "unauthenticated", "no")} />);
    expect(screen.getByRole("link", { name: "Sign in again" })).toBeTruthy();
    render(<ErrorState error={new ApiError(0, "network", "Connection lost.")} />);
    expect(screen.getByText("Connection interrupted")).toBeTruthy();
  });
});

function Tabs() {
  const [v, setV] = useState<"a" | "b" | "c">("a");
  return (<>
    <TabList id="t" label="Views" value={v} onChange={setV} tabClassName={() => ""}
      tabs={[{ key: "a", label: "Alpha" }, { key: "b", label: "Beta", disabled: true }, { key: "c", label: "Gamma" }]} />
    <TabPanel id="t" value={v}>panel {v}</TabPanel>
  </>);
}

describe("tabs (P3-FE-09)", () => {
  it("link tab and panel, keep one tab stop, and move with the arrow keys past disabled tabs", () => {
    render(<Tabs />);
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha.getAttribute("aria-controls")).toBe("t-panel");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe("t-tab-a");
    expect([alpha.tabIndex, screen.getByRole("tab", { name: "Gamma" }).tabIndex]).toEqual([0, -1]);
    fireEvent.keyDown(alpha, { key: "ArrowRight" });
    const gamma = screen.getByRole("tab", { name: "Gamma" });
    expect(gamma.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(gamma);
    expect(screen.getByRole("tabpanel").textContent).toBe("panel c");
    fireEvent.keyDown(gamma, { key: "Home" });
    expect(screen.getByRole("tab", { name: "Alpha" }).getAttribute("aria-selected")).toBe("true");
  });
});
