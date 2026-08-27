import { Navigate, Route, Routes } from "react-router-dom";
import { useSession } from "./lib/session";
import { Shell } from "./components/Shell";
import { SignIn } from "./screens/SignIn";
import { Today } from "./screens/Today";
import { Calendar } from "./screens/Calendar";
import { Study } from "./screens/Study";
import { Context } from "./screens/Context";

function Guarded({ children }: { children: React.ReactNode }) {
  const { account, ready } = useSession();

  if (!ready) return <div className="min-h-dvh" />;
  if (!account) return <Navigate to="/entrar" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/entrar" element={<SignIn />} />
      <Route
        path="/hoje"
        element={
          <Guarded>
            <Today />
          </Guarded>
        }
      />
      <Route
        path="/calendario"
        element={
          <Guarded>
            <Calendar />
          </Guarded>
        }
      />
      <Route
        path="/estudo"
        element={
          <Guarded>
            <Study />
          </Guarded>
        }
      />
      <Route
        path="/contexto"
        element={
          <Guarded>
            <Context />
          </Guarded>
        }
      />
      <Route path="*" element={<Navigate to="/hoje" replace />} />
    </Routes>
  );
}
