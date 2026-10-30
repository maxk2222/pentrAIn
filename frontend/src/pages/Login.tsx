import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "@/lib/api";
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui";

interface Token { token: string }

export function LoginPage() {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await api.post<Token>("/api/auth/login", { password: pw });
      setToken(r.token);
      nav("/");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid h-full place-items-center bg-background">
      <Card className="w-[380px]">
        <CardHeader className="items-center pt-8">
          <img src="/logo.png" alt="pentrAIn" className="mb-1 h-24 w-auto" />
          <CardTitle className="sr-only">pentrAIn</CardTitle>
          <p className="text-sm text-muted">Pentest training range + AI coach</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3 pb-4">
            <Input type="password" placeholder="Admin password" value={pw}
              onChange={(e) => setPw(e.target.value)} autoFocus />
            {err && <p className="text-sm text-danger">{err}</p>}
            <Button className="w-full" disabled={busy || !pw}>Sign in</Button>
            <p className="text-center text-xs text-muted">First sign-in sets the admin password.</p>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
