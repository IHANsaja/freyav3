"use client";
import { createContext, useContext } from "react";
import { useFreyaSocketConnection } from "../hooks/useFreyaSocket";
const Context = createContext<ReturnType<
  typeof useFreyaSocketConnection
> | null>(null);
export function FreyaSocketProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const connection = useFreyaSocketConnection();
  return <Context.Provider value={connection}>{children}</Context.Provider>;
}
export function useSharedFreyaSocket() {
  const value = useContext(Context);
  if (!value) throw new Error("FreyaSocketProvider missing");
  return value;
}
