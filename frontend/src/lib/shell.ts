import { useOutletContext } from "react-router-dom";

export interface ShellContext {
  openAddSite: () => void;
}

/** Actions the app shell offers to the page it renders. */
export function useShell() {
  return useOutletContext<ShellContext>();
}
