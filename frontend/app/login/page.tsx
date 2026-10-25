"use client";

import { useState, type FormEvent, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { conversationApi } from "@/features/conversation/api";
import { isAppError, setApiKey } from "@/lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    // 公开演示无需用户提供密钥；旧 /login 链接也直接返回工作台。
    conversationApi.me().then(() => router.replace("/")).catch(() => setChecking(false));
  }, [router]);

  async function login(event: FormEvent) {
    event.preventDefault();
    const value = key.trim();
    if (!value || loading) return;
    setLoading(true); setError(null); setApiKey(value);
    try {
      await conversationApi.me();
      router.replace("/");
    } catch (e) {
      setApiKey("");
      setError(isAppError(e) ? e.userMessage : "登录失败");
      setLoading(false);
    }
  }

  if (checking) return <main className="min-h-screen grid place-items-center text-muted">正在打开行策工作台…</main>;

  return (
    <main className="min-h-screen grid place-items-center bg-canvas p-4">
      <Card className="w-full max-w-md">
        <CardHeader><span className="inline-flex items-center gap-2"><ShieldCheck className="size-5 text-primary" />登录行策工作台</span></CardHeader>
        <CardBody>
          <form onSubmit={login} className="space-y-4">
            <p className="text-sm text-muted">请输入管理员分配给你的 API Key。凭证只保存在当前浏览器标签页，关闭标签页后自动清除。</p>
            <label className="block text-xs text-muted">API Key
              <input type="password" autoComplete="current-password" className="control text-sm" value={key}
                onChange={(e) => setKey(e.target.value)} minLength={16} required autoFocus />
            </label>
            {error && <Alert tone="danger">{error}</Alert>}
            <Button type="submit" className="w-full" loading={loading}>验证并登录</Button>
          </form>
        </CardBody>
      </Card>
    </main>
  );
}
