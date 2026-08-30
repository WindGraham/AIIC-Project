"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type Me = { username: string } | null;

export default function Nav({ me }: { me: Me }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<Me>(me);

  useEffect(() => {
    setUser(me);
  }, [me]);

  async function doLogout() {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    setUser(null);
    router.push("/login");
    router.refresh();
  }

  if (pathname === "/login") return null;

  const links = [
    { href: "/", label: "首页" },
    { href: "/resumes", label: "管理简历" },
    { href: "/booking", label: "预约面试" },
    { href: "/interviews", label: "面试列表" },
    { href: "/self-test", label: "功能测试" },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-[#0b0b0f]/90 backdrop-blur">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/" className="font-semibold text-white">ProbeDesk</Link>
          <nav className="flex items-center gap-1 text-sm">
            {links.map((l) => (
              <Link key={l.href} href={l.href}
                className={`px-3 py-1.5 rounded-lg hover:text-white transition ${
                  pathname === l.href ? "text-white bg-white/10" : "text-white/60"
                }`}>
                {l.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {user ? (
            <>
              <span className="text-white/60">👤 {user.username}</span>
              <button onClick={doLogout} className="rounded-lg border border-white/10 px-3 py-1.5 text-white/70 hover:text-white">
                退出
              </button>
            </>
          ) : (
            <Link href="/login" className="rounded-lg bg-indigo-500 px-3 py-1.5 text-white">登录</Link>
          )}
        </div>
      </div>
    </header>
  );
}
