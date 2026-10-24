import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as clerk from "@clerk/clerk-react";
import {
  AuthenticateWithRedirectCallback,
  ClerkProvider,
  LOCAL_USER_ID,
  SignedIn,
  SignedOut,
  UserButton,
  useAuth,
  useSignIn,
  useSignUp,
} from "../auth-local";

describe("auth-local shim", () => {
  it("is what '@clerk/clerk-react' resolves to when no Clerk key is set", () => {
    // The vitest config applies the same alias as the dev server and the build.
    expect(clerk.useAuth).toBe(useAuth);
    expect(clerk.SignedIn).toBe(SignedIn);
  });

  it("reports an always signed-in local user", () => {
    const auth = useAuth();
    expect(auth.isLoaded).toBe(true);
    expect(auth.isSignedIn).toBe(true);
    expect(auth.userId).toBe(LOCAL_USER_ID);
  });

  it("issues no token, so no Authorization header is sent", async () => {
    await expect(useAuth().getToken()).resolves.toBeNull();
  });

  it("keeps getToken stable across calls (App uses it as an effect dependency)", () => {
    expect(useAuth().getToken).toBe(useAuth().getToken);
  });

  it("renders SignedIn children and hides SignedOut children", () => {
    render(
      <ClerkProvider publishableKey="ignored">
        <SignedIn>
          <span>signed-in content</span>
        </SignedIn>
        <SignedOut>
          <span>signed-out content</span>
        </SignedOut>
      </ClerkProvider>
    );
    expect(screen.getByText("signed-in content")).toBeInTheDocument();
    expect(screen.queryByText("signed-out content")).not.toBeInTheDocument();
  });

  it("renders nothing for the user button and the SSO callback", () => {
    const { container } = render(
      <>
        <UserButton />
        <AuthenticateWithRedirectCallback />
      </>
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("gives the sign-in and sign-up hooks inert, not-loaded state", () => {
    expect(useSignIn().isLoaded).toBe(false);
    expect(useSignUp().isLoaded).toBe(false);
  });
});
