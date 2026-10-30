import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import ChatPage from "./components/chat/ChatPage";
import NewChatPage from "./components/chat/NewChatPage";
import Layout from "./components/shell/Layout";
import { Spinner } from "./components/ui";
import WorkspacesHome from "./components/WorkspacesHome";
import { useShell } from "./lib/shell";

// Inspection and settings views are visited less; keep them out of the
// bundle that has to load before the first question can be asked.
const SitePage = lazy(() => import("./components/site/SitePage"));
const SettingsPage = lazy(() => import("./components/settings/SettingsPage"));

const later = (node: ReactNode) => (
  <Suspense fallback={<div className="p-10 text-muted"><Spinner /></div>}>{node}</Suspense>
);

function Home() {
  const { openAddSite } = useShell();
  return <NewChatPage onAddSite={openAddSite} />;
}

/** Links from before the redesign (`/w/:id/chat`, `/w/:id/lab`, …). */
function LegacyWorkspace() {
  const { workspaceId, "*": rest } = useParams();
  const tab = (rest ?? "").split("/")[0];
  if (!tab || tab === "chat") return <Navigate to={`/?site=${workspaceId}`} replace />;
  return <Navigate to={`/sites/${workspaceId}/${tab}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="c/:sessionId" element={<ChatPage />} />
        <Route path="sites" element={<WorkspacesHome />} />
        <Route path="sites/:workspaceId" element={<Navigate to="lab" replace />} />
        <Route path="sites/:workspaceId/:tab" element={later(<SitePage />)} />
        <Route path="settings" element={<Navigate to="/settings/models" replace />} />
        <Route path="settings/:section" element={later(<SettingsPage />)} />
        <Route path="w/:workspaceId/*" element={<LegacyWorkspace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
