import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ signIn: vi.fn().mockResolvedValue(undefined) }));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ signIn: mocks.signIn }),
}));

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("submits values present in the form, including browser-autofilled credentials", async () => {
    render(<LoginPage />);
    const username = screen.getByLabelText("Username") as HTMLInputElement;
    const password = screen.getByLabelText("Password") as HTMLInputElement;
    username.value = "autofilled-user";
    password.value = "autofilled-password";

    fireEvent.submit(screen.getByRole("button", { name: /sign in/i }).closest("form")!);

    await waitFor(() => expect(mocks.signIn).toHaveBeenCalledWith("autofilled-user", "autofilled-password"));
  });
});
