/**
 * Root component.
 *
 * Auth gates everything: until useAuth reports a signed-in user, the only thing
 * that renders is Login (NFR-04).
 *
 * The email list is still the placeholder fixture set. Step 4 replaces this
 * with GET /api/inbox; nothing below the shell needs to change when it does,
 * because Dashboard already takes emails as a prop.
 */

import { AuthProvider, useAuth } from "./hooks/useAuth.jsx";
import Dashboard from "./components/Dashboard.jsx";
import Login from "./views/Login.jsx";
import { MOCK_EMAILS } from "./lib/mockEmails.js";

function Shell() {
  const { user, signOut } = useAuth();

  if (!user) return <Login />;
  return <Dashboard user={user} emails={MOCK_EMAILS} onLogout={signOut} />;
}

export default function App() {
  return (
    <div className="iq" style={{ height: "100vh" }}>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </div>
  );
}
