"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/home" : "/login");
  }, [router]);
  return (
    <div className="loading-page">
      <div className="spinner" />
    </div>
  );
}
