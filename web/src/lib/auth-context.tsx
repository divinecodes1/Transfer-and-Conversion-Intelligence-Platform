import * as React from "react";
import {
  authenticatedUser,
  authenticationMode,
  createAccount,
  manageAccount,
  reauthenticate,
  signOut,
  type AuthenticatedUser,
  type AuthenticationMode,
} from "./auth";

type AuthContextValue = {
  mode: AuthenticationMode;
  user: AuthenticatedUser | null;
  login: () => Promise<void>;
  register: () => Promise<void>;
  account: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const value = React.useMemo<AuthContextValue>(
    () => ({
      mode: authenticationMode,
      user: authenticatedUser(),
      login: reauthenticate,
      register: createAccount,
      account: manageAccount,
      logout: signOut,
    }),
    [],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth() {
  const value = React.use(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
