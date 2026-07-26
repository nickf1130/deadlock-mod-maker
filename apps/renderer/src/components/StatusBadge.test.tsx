import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders camel-case backend statuses as accessible icons", () => {
    render(<StatusBadge status="capabilityUnavailable" />);
    expect(screen.getByLabelText("Capability Unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Capability Unavailable")).not.toBeInTheDocument();
  });
});
