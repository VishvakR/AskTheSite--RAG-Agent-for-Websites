import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import WorkspacesHome from "./components/WorkspacesHome";
import ChatTab from "./components/ChatTab";
import RetrievalLabTab from "./components/RetrievalLabTab";
import DocumentsTab from "./components/DocumentsTab";
import ApiTab from "./components/ApiTab";
import { Spinner } from "./components/ui";

// react-force-graph pulls in the whole d3 stack; keep it out of the main bundle.
const GraphTab = lazy(() => import("./components/GraphTab"));

const shell = (children: ReactNode) => <AppShell>{children}</AppShell>;

export default function App() {
  return (
    <Routes>
      <Route path="/" element={shell(<WorkspacesHome />)} />
      <Route path="/w/:workspaceId" element={<Navigate to="chat" replace />} />
      <Route path="/w/:workspaceId/chat" element={shell(<ChatTab />)} />
      <Route path="/w/:workspaceId/lab" element={shell(<RetrievalLabTab />)} />
      <Route
        path="/w/:workspaceId/graph"
        element={shell(
          <Suspense
            fallback={
              <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted">
                <Spinner /> Loading graph…
              </div>
            }
          >
            <GraphTab />
          </Suspense>,
        )}
      />
      <Route path="/w/:workspaceId/documents" element={shell(<DocumentsTab />)} />
      <Route path="/w/:workspaceId/api" element={shell(<ApiTab />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
