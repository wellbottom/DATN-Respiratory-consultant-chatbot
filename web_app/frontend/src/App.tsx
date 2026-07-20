import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, Link } from "react-router-dom";
import { ClerkProvider } from "@clerk/react";
import { viVN } from "@clerk/localizations";
import { Sparkles, Info, RefreshCw } from "lucide-react";

import { API_BASE, requestJson } from "./utils/api";
import { Show } from "./components/Show";
import { AppShell } from "./components/AppShell";
import { useLang } from "./i18n";

// Views importing
import { Marketing } from "./views/Marketing";
import { HomeHub } from "./views/HomeHub";
import { ChatWorkspace } from "./views/ChatWorkspace";
import { Community } from "./views/Community";
import { FindCare } from "./views/FindCare";
import { SharedConversation } from "./views/SharedConversation";

interface PublicConfig {
  clerkPublishableKey: string;
  clerkEnabled: boolean;
  allowedOrigins?: string[];
}

export default function App() {
  const { t } = useLang();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [isBooting, setIsBooting] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);

  // Boot Sequence on Load
  const fetchPublicConfig = async () => {
    setIsBooting(true);
    setBootError(null);
    try {
      // Endpoint is public, no auth needed
      const data: PublicConfig = await requestJson(API_BASE, "/api/config/public", {
        method: "GET",
        includeAuth: false
      });
      setConfig(data);
    } catch (e: any) {
      console.error("Boot configuration extraction failed", e);
      setBootError(t("Không thể kết nối với máy chủ quản lý cấu hình HealthyLung. Vui lòng kiểm tra lại dịch vụ mạng."));
    } finally {
      setIsBooting(false);
    }
  };

  useEffect(() => {
    fetchPublicConfig();
  }, []);

  // Theme configuration for Clerk modals
  const clerkAppearance = {
    variables: {
      colorPrimary: "#0E9E8C",
      colorText: "#0C1A1F",
      colorBackground: "#FFFFFF",
      colorInputBackground: "#FFFFFF",
      borderRadius: "16px",
      fontFamily: '"Inter", sans-serif'
    }
  };

  // 1) Show Branded Loading Boot Screen
  if (isBooting) {
    return (
      <div className="marketing-hero" style={{ minHeight: "100vh" }} id="boot-loader-screen">
        <div className="marketing-blob"></div>
        <div className="marketing-card" style={{ maxWidth: "480px", padding: "48px" }}>
          <div className="logo-spark" style={{ width: "56px", height: "56px", fontSize: "24px" }} id="boot-logo-launcher">
            <Sparkles />
          </div>
          <h2 className="h2" style={{ marginTop: "12px" }}>HealthyLung AI</h2>
          <div className="thinking-shimmer" style={{ width: "40px" }} id="boot-dots">
            <div className="dot"></div>
            <div className="dot"></div>
            <div className="dot"></div>
          </div>
          <span className="caption" style={{ color: "var(--brand-600)", fontWeight: 600 }}>
            {t("Đang tải dữ liệu chăm sóc lâm sàng...")}
          </span>
        </div>
      </div>
    );
  }

  // 2) Show Retry screen on critical fetch failures
  if (bootError) {
    return (
      <div className="marketing-hero" style={{ minHeight: "100vh" }} id="boot-error-screen">
        <div className="marketing-card" style={{ maxWidth: "520px", padding: "48px" }}>
          <div className="logo-spark" style={{ background: "var(--danger)", width: "56px", height: "56px", fontSize: "24px" }}>
            ⚠️
          </div>
          <h2 className="h2" style={{ marginTop: "16px" }}>{t("Lỗi kết nối máy chủ")}</h2>
          <p className="caption" style={{ margin: "12px 0", color: "var(--ink-500)", fontSize: "0.95rem" }}>
            {bootError}
          </p>
          <button onClick={fetchPublicConfig} className="btn btn-primary btn-pill flex-center gap-8 mt-16" id="btn-retry-boot">
            <RefreshCw style={{ width: "16px", height: "16px" }} />
            <span>{t("Thử kết nối lại")}</span>
          </button>
        </div>
      </div>
    );
  }

  // 3) Handle Missing-Clerk keys or deactivated authentication flows
  const hasClerkKey = config && config.clerkPublishableKey && config.clerkPublishableKey.trim().length > 0;
  
  if (!hasClerkKey || !config?.clerkEnabled) {
    // Render the custom Missing Clerk screen, but still mount public routing for Shared Readonly Conversations
    return (
      <BrowserRouter>
        <Routes>
          {/* Shared read-only views work flawlessly without authentication */}
          <Route path="/share/:conversationId" element={<SharedConversation />} />

          {/* Any other routes redirect to clerk config warning panel */}
          <Route
            path="*"
            element={
              <div className="marketing-hero" style={{ minHeight: "100vh" }} id="missing-clerk-screen">
                <div className="marketing-card" style={{ maxWidth: "620px", padding: "56px 48px" }}>
                  <div className="logo-spark" style={{ background: "var(--warning)", width: "60px", height: "60px", fontSize: "28px" }}>
                    ⚙️
                  </div>
                  <h2 className="h2" style={{ marginTop: "16px" }}>{t("Thiếu cấu hình đăng nhập (Clerk)")}</h2>
                  <p className="caption" style={{ fontSize: "1rem", color: "var(--ink-700)", margin: "12px 0" }}>
                    {t("Cuộc trò chuyện này yêu cầu tài khoản người dùng bỉm sữa được xác thực bằng hệ thống ")}<strong>Clerk Auth</strong>{t(". Tuy nhiên, khóa công khai ")}<code>VITE_CLERK_PUBLISHABLE_KEY</code>{t(" chưa được thiết lập từ xa trên máy chủ HealthyLung.")}
                  </p>
                  <div className="safety-warning-card" style={{ width: "100%", textAlign: "left" }}>
                    <div className="safety-header-label">
                      <Info style={{ color: "var(--info)" }} />
                      {t("Hướng dẫn cấu hình dành cho nhà phát triển:")}
                    </div>
                    <span className="caption" style={{ fontSize: "0.8125rem" }}>
                      {t("1. Thiết lập biến môi trường ")}<code>VITE_CLERK_PUBLISHABLE_KEY</code>{t(" trong cài đặt bí mật hoặc file ")}<code>.env</code>.<br />
                      {t("2. Đảm bảo dịch vụ ")}<code>clerkEnabled</code>{t(" trả về giá trị ")}<code>true</code>{t(" trên API cấu hình của bạn.")}
                    </span>
                  </div>

                  {/* Public shared placeholder link access */}
                  <div className="mt-16 text-center">
                    <p className="caption" style={{ marginBottom: "8px" }}>{t("Bạn vẫn có thể kiểm tra một đường liên kết chia sẻ công khai mẫu:")}</p>
                    <Link to="/share/sample-convo-id" className="btn btn-secondary btn-pill text-center">
                      {t("Xem cuộc trò chuyện chia sẻ mẫu")}
                    </Link>
                  </div>
                </div>
              </div>
            }
          />
        </Routes>
      </BrowserRouter>
    );
  }

  // 4) Clean, Standard Authentication Render Flow
  return (
    <ClerkProvider
      publishableKey={config.clerkPublishableKey}
      localization={viVN}
      appearance={clerkAppearance}
    >
      <BrowserRouter>
        <Routes>
          {/* A. Read-Only public routing (works completely signed-out too) */}
          <Route path="/share/:conversationId" element={<SharedConversation />} />

          {/* B. General Application Routes */}
          <Route
            path="/*"
            element={
              <>
                {/* Visual state shown if the user is authenticated */}
                <Show when="signed-in">
                  <AppShell>
                    <Routes>
                      <Route path="/" element={<HomeHub />} />
                      <Route path="/chat" element={<ChatWorkspace />} />
                      <Route path="/community" element={<Community />} />
                      <Route path="/find-care" element={<FindCare />} />
                      {/* Wildcard Fallback redirects home */}
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </AppShell>
                </Show>

                {/* Visual state shown if the user is signed out */}
                <Show when="signed-out">
                  <Marketing clerkEnabled={config.clerkEnabled} />
                </Show>
              </>
            }
          />
        </Routes>
      </BrowserRouter>
    </ClerkProvider>
  );
}
