import React from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { UserButton } from "@clerk/react";
import { Home, MessageSquare, Users, MapPin, Sparkles } from "lucide-react";
import { LangToggle, useLang } from "../i18n";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useLang();
  const currentPath = location.pathname;

  // Derive section badge
  let sectionName = t("Trang chủ");
  if (currentPath === "/chat") sectionName = t("Trò chuyện");
  else if (currentPath === "/community") sectionName = t("Cộng đồng");
  else if (currentPath === "/find-care") sectionName = t("Bản đồ Nhi");

  const navItems = [
    { path: "/", label: t("Trang chủ"), icon: Home },
    { path: "/chat", label: t("Trò chuyện"), icon: MessageSquare },
    { path: "/community", label: t("Cộng đồng"), icon: Users },
    { path: "/find-care", label: t("Tìm nơi giữ trẻ"), icon: MapPin },
  ];

  return (
    <div className="app-container" id="lumen-app-shell">
      {/* Universal Top Navigation Header */}
      <header className="top-bar" id="app-top-navigation">
        <div className="brand-section" id="top-branding">
          <Link to="/" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: "10px" }}>
            <div className="logo-spark" id="brand-logo-disc">
              <Sparkles style={{ width: "16px", height: "16px" }} />
            </div>
            <span className="brand-title" id="brand-words">
              HealthyLung
              <span className="brand-badge" id="current-section-badge">
                {sectionName}
              </span>
            </span>
          </Link>
        </div>

        {/* Center Desktop Navigation */}
        <nav className="desktop-nav" id="desktop-menubar" aria-label="Desktop Primary Menu">
          {navItems.map((item) => {
            const IconComponent = item.icon;
            const isActive = currentPath === item.path || (item.path !== "/" && currentPath.startsWith(item.path));
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`nav-link ${isActive ? "active" : ""}`}
                id={`desktop-nav-${item.path.replace("/", "root")}`}
              >
                <IconComponent style={{ width: "18px", height: "18px" }} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Right Authentication Action Panel */}
        <div className="right-user-control" id="clerk-user-avatar-trigger" style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <LangToggle />
          <UserButton />
        </div>
      </header>

      {/* Main Viewport Workspace */}
      <main className="main-content" id="app-main-viewport">
        {children}
      </main>

      {/* Persistent Bottom Tab Bar on Mobile */}
      <nav className="mobile-nav" id="mobile-tabbar-nav" aria-label="Mobile Navigation Drawer">
        <ul className="mobile-nav-list" id="mobile-tab-list">
          {navItems.map((item) => {
            const IconComponent = item.icon;
            const isActive = currentPath === item.path || (item.path !== "/" && currentPath.startsWith(item.path));
            return (
              <li key={item.path} className="mobile-nav-item">
                <Link
                  to={item.path}
                  className={`mobile-nav-link ${isActive ? "active" : ""}`}
                  id={`mobile-link-${item.path.replace("/", "root")}`}
                >
                  {isActive && <div className="inline-pill-indicator"></div>}
                  <IconComponent />
                  <span>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
