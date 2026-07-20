import React from "react";
import { useAuth } from "@clerk/react";

interface ShowProps {
  when: "signed-in" | "signed-out";
  children: React.ReactNode;
}

export function Show({ when, children }: ShowProps) {
  const { isSignedIn, isLoaded } = useAuth();

  // If auth state is not loaded yet, wait silently or return null to prevent screen flashing
  if (!isLoaded) {
    return null;
  }

  if (when === "signed-in" && isSignedIn) {
    return <>{children}</>;
  }

  if (when === "signed-out" && !isSignedIn) {
    return <>{children}</>;
  }

  return null;
}
