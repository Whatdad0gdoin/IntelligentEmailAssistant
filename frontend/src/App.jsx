/**
 * Root component.
 *
 * Auth gates everything: until useAuth reports a signed-in user, the only view
 * that renders is Login (NFR-04). The inbox and its emails are fetched from the
 * API after sign-in -- there is no placeholder data in the app any more.
 */

import { AuthProvider, useAuth } from "./hooks/useAuth.jsx";
import Dashboard from "./components/Dashboard.jsx";
import Login from "./views/Login.jsx";

function Shell() {
  const { user, signOut } = useAuth();
  if (!user) return <Login />;
  return <Dashboard user={user} onLogout={signOut} />;
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
