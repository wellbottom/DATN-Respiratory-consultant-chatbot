import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles,
  ExternalLink,
  ShieldCheck,
  Calendar,
  X,
  MessageSquare,
  Home,
  Info
} from "lucide-react";

import { API_BASE, requestJson } from "../utils/api";
import { SourceDetailsModal } from "../components/SourceDetailsModal";
import {
  ConversationDetail,
  ConversationMessage,
  RouteDebug,
  SourceSection,
  INTENT_LABELS,
  CORPUS_LABELS,
  COLLECTION_LABELS,
  SECTION_TYPE_LABELS,
  getLabel
} from "../types";
import { LangToggle, useLang } from "../i18n";

export function SharedConversation() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const { t } = useLang();

  // Core content states
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorCode, setErrorCode] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Inspector States (Read Only Details Drawer)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [inspectorRoute, setInspectorRoute] = useState<RouteDebug | null>(null);
  const [inspectorSources, setInspectorSources] = useState<SourceSection[]>([]);
  const [selectedSource, setSelectedSource] = useState<SourceSection | null>(null);
  const [selectedSourceLabel, setSelectedSourceLabel] = useState("");

  // Localized date formatter
  const formatIsoDate = (isoString?: string) => {
    if (!isoString) return "";
    try {
      const date = new Date(isoString);
      return new Intl.DateTimeFormat("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "2-digit",
        year: "numeric"
      }).format(date);
    } catch {
      return isoString;
    }
  };

  useEffect(() => {
    const fetchSharedThread = async () => {
      if (!conversationId) return;
      setIsLoading(true);
      setErrorCode(null);
      setErrorMessage(null);

      try {
        const response: ConversationDetail = await requestJson(
          API_BASE,
          `/api/conversations/${conversationId}`,
          {
            method: "GET",
            includeAuth: false // Access publicly
          }
        );
        setDetail(response);

        // Pre-focus last assistant message to populate inspecting sidebar
        const assistantMsg = response.messages.filter((m) => m.role === "assistant");
        if (assistantMsg.length > 0) {
          const lastMsg = assistantMsg[assistantMsg.length - 1];
          setSelectedMessageId(lastMsg.id);
          setInspectorRoute(lastMsg.route || null);
          setInspectorSources(lastMsg.sources || []);
        }
      } catch (err: any) {
        console.error("Failure fetching shared public child conversation", err);
        setErrorCode(err.status || 500);

        if (err.status === 403) {
          setErrorMessage(t("Liên kết chia sẻ này hiện không khả dụng."));
        } else if (err.status === 404) {
          setErrorMessage(t("Không tìm thấy cuộc trò chuyện được chia sẻ."));
        } else {
          setErrorMessage(t("Đã xảy ra lỗi không thể xác định khi kết nối với máy chủ."));
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchSharedThread();
  }, [conversationId]);

  // Click handler to view sources
  const handleSelectMessageReadOnly = (msg: ConversationMessage) => {
    if (msg.role === "assistant") {
      setSelectedMessageId(msg.id);
      setInspectorRoute(msg.route || null);
      setInspectorSources(msg.sources || []);
      // Open Slide over drawer when on small devices
      if (window.innerWidth <= 900) {
        setIsDrawerOpen(true);
      }
    }
  };

  return (
    <div className="share-readonly-layout" id="share-view-container">
      {/* 1) Minimal Top Bar */}
      <header className="top-bar" id="share-minimalist-header">
        <div className="brand-section">
          <Link to="/" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: "10px" }}>
            <div className="logo-spark">
              <Sparkles style={{ width: "16px", height: "16px" }} />
            </div>
            <span className="brand-title">HealthyLung</span>
          </Link>
          <span className="brand-badge" style={{ backgroundColor: "var(--intel-50)", color: "var(--intel-500)" }}>
            {t("Bản Chia Sẻ")}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <LangToggle />
          <button onClick={() => navigate("/")} className="btn btn-secondary btn-pill" id="action-exit-share">
            <Home style={{ width: "14px", height: "14px" }} />
            <span>{t("Về trang chính")}</span>
          </button>
        </div>
      </header>

      {/* Handling Loading States */}
      {isLoading ? (
        <div className="marketing-hero">
          <div className="marketing-card flex-center gap-16" style={{ padding: "48px" }}>
            <div className="thinking-shimmer" style={{ width: "40px" }}>
              <div className="dot"></div>
              <div className="dot"></div>
              <div className="dot"></div>
            </div>
            <span className="caption">{t("Đang bảo mật nạp dữ liệu chia sẻ...")}</span>
          </div>
        </div>
      ) : errorMessage ? (
        /* Error fallback cases */
        <div className="marketing-hero">
          <div className="marketing-card" style={{ padding: "56px 40px", maxWidth: "580px" }}>
            <div
              className="logo-spark"
              style={{ background: "var(--danger)", width: "56px", height: "56px", fontSize: "24px" }}
            >
              ⚠️
            </div>
            <h2 className="h2" style={{ marginTop: "16px" }}>
              {t("Truy cập thất bại")}
            </h2>
            <p className="caption" style={{ fontSize: "1rem", color: "var(--ink-500)", margin: "8px 0" }}>
              {errorMessage}
            </p>
            <button onClick={() => navigate("/")} className="btn btn-primary btn-pill mt-16">
              {t("Quay lại Trang chủ")}
            </button>
          </div>
        </div>
      ) : detail ? (
        <>
          {/* Public Banner details */}
          <section className="share-public-banner" id="convo-meta-banner">
            <div className="share-banner-details">
              <Calendar style={{ width: "16px", height: "16px" }} />
              <span>
                {t("Ngày chia sẻ công khai: {date} · {n} lượt hội thoại", { date: formatIsoDate(detail.created_at), n: detail.message_count })}
              </span>
            </div>
            <div style={{ display: "none" }}>Hidden read-only status code</div>
          </section>

          {/* Core double column perspective */}
          <div className="share-readonly-body" id="share-body-layout">
            {/* Left/Center Thread Read Only */}
            <div className="share-readonly-thread" id="share-thread-timeline">
              <div style={{ paddingBottom: "12px", borderBottom: "1px solid var(--line)", marginBottom: "16px" }}>
                <span className="overline" style={{ color: "var(--brand-600)" }}>{t("Chủ đề thảo luận")}</span>
                <h1 className="h1" style={{ margin: "4px 0", fontSize: "1.65rem", color: "var(--ink-900)" }}>
                  {detail.title || t("Tư vấn Nhi khoa")}
                </h1>
              </div>

              {detail.messages.map((item) => {
                const isUser = item.role === "user";
                const isSelected = selectedMessageId === item.id;

                return (
                  <div
                    key={item.id}
                    className={`message-bubble-row ${isUser ? "user" : "assistant"} ${
                      isSelected ? "selected" : ""
                    }`}
                    id={`readonly-msg-${item.id}`}
                    role={!isUser ? "button" : undefined}
                    tabIndex={!isUser ? 0 : undefined}
                    onClick={() => handleSelectMessageReadOnly(item)}
                    onKeyDown={(e) => {
                      if (!isUser && (e.key === "Enter" || e.key === " ")) {
                        e.preventDefault();
                        handleSelectMessageReadOnly(item);
                      }
                    }}
                    style={{ cursor: !isUser ? "pointer" : "default" }}
                  >
                    <span className="bubble-meta-label">
                      {isUser ? t("Người dùng chia sẻ") : t("HealthyLung AI tư vấn")} · {formatIsoDate(item.created_at)}
                      {!isUser && (
                        <span className="pill-sm" style={{ backgroundColor: "var(--brand-5)", color: "var(--brand-600)", border: "1px solid var(--line)", fontSize: "0.6875rem", display: "inline-flex", alignItems: "center", gap: "2px" }}>
                          {t("🔍 Nhấp xem nguồn")}
                        </span>
                      )}
                    </span>
                    <div className="bubble-text-box">
                      <div className="markdown-body">
                        <Markdown remarkPlugins={[remarkGfm]}>{item.content}</Markdown>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Right Side Source display (Read-Only) */}
            <aside className="sidebar-sources" id="share-detail-inspector">
              <div className="sources-header-box">
                <span className="overline">{t("Kiểm Định Y Văn (Read-Only)")}</span>
              </div>
              <div className="sources-scroll-area">
                {inspectorRoute || inspectorSources.length > 0 ? (
                  <>
                    {/* Routed intents */}
                    {inspectorRoute && (
                      <div className="route-debug-card">
                        <span className="caption" style={{ fontWeight: 700, color: "var(--intel-500)" }}>
                          {t("Phán đoán trọng điểm:")} {t(getLabel(inspectorRoute.intent, INTENT_LABELS))}
                        </span>
                        <div className="provider-tags-flow" style={{ marginTop: "4px" }}>
                          {inspectorRoute.collection_name && (
                            <span className="pill-sm pill-public">
                              {t(getLabel(inspectorRoute.collection_name, COLLECTION_LABELS))}
                            </span>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Standard safety warning panel */}
                    <div className="safety-warning-card">
                      <div className="safety-header-label">
                        <ShieldCheck style={{ color: "var(--danger)" }} />
                        {t("Cảnh báo Nhi khoa Lâm sàng")}
                      </div>
                      <span className="caption" style={{ fontSize: "0.8125rem", color: "var(--ink-700)" }}>
                        {t("Nội dung chia sẻ chỉ có ý nghĩa tham khảo. Nếu bé mệt sâu, li bì, mất nước nặng hay co giật, cần nhanh chóng liên hệ với cơ sở cấp cứu y tế gần nhất.")}
                      </span>
                    </div>

                    {/* Sources details scroll */}
                    {inspectorSources.length > 0 && (
                      <div>
                        <span className="overline" style={{ display: "block", marginBottom: "12px" }}>
                          {t("Y văn đối sánh y tế ({n})", { n: inspectorSources.length })}
                        </span>
                        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                          {inspectorSources.map((source, idx) => {
                            const sourceLabel = `Source ${idx + 1}`;

                            return (
                              <div
                                key={idx}
                                className="source-section-card source-section-card-clickable"
                                role="button"
                                tabIndex={0}
                                onClick={() => {
                                  setSelectedSource(source);
                                  setSelectedSourceLabel(sourceLabel);
                                }}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    setSelectedSource(source);
                                    setSelectedSourceLabel(sourceLabel);
                                  }
                                }}
                              >
                                <div className="confidence-row">
                                  <span className="overline" style={{ fontSize: "0.65rem", color: "var(--brand-600)" }}>
                                    {t(getLabel(source.corpus, CORPUS_LABELS))}
                                  </span>
                                </div>
                                <h4 className="caption" style={{ fontWeight: 700, color: "var(--ink-900)" }}>
                                  {sourceLabel}
                                </h4>
                                {source.h2 && (
                                  <div className="source-breadcrumb-row" style={{ fontSize: "0.75rem" }}>
                                    ↳ {source.h2}
                                  </div>
                                )}
                                {source.source_url && (
                                  <a
                                    href={source.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="btn btn-secondary btn-pill"
                                    style={{ padding: "4px 8px", fontSize: "0.7rem", marginTop: "4px", width: "100%", display: "inline-flex", justifyContent: "center" }}
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    <ExternalLink style={{ width: "10px", height: "10px" }} />
                                    {t("Xem bài viết từ Vinmec")}
                                  </a>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="sources-empty-state">
                    <MessageSquare style={{ color: "var(--ink-300)" }} />
                    <span className="caption">{t("Chọn một bong bóng phản hồi ở luồng để nạp chứng thực y khoa.")}</span>
                  </div>
                )}
              </div>
            </aside>
          </div>

          {/* Mobile responsive slide-over drawer details */}
          {isDrawerOpen && (
            <div className="drawer-scrim" onClick={() => setIsDrawerOpen(false)}>
              <div
                className="drawer-slide-content right"
                id="share-mobile-drawer"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="drawer-header">
                  <span className="overline" style={{ color: "var(--ink-900)" }}>
                    {t("Chứng thực tài liệu")}
                  </span>
                  <button onClick={() => setIsDrawerOpen(false)} aria-label={t("Đóng")}>
                    <X />
                  </button>
                </div>
                <div className="drawer-body-scroll" style={{ padding: "16px" }}>
                  {inspectorRoute && (
                    <div className="route-debug-card" style={{ marginBottom: "12px" }}>
                      <span className="caption" style={{ fontWeight: 700, color: "var(--intel-500)" }}>
                        {t("Phán đoán:")} {t(getLabel(inspectorRoute.intent, INTENT_LABELS))}
                      </span>
                    </div>
                  )}

                  {inspectorSources.map((source, index) => (
                    <div
                      key={index}
                      className="source-section-card source-section-card-clickable"
                      style={{ margin: "8px 0" }}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        setSelectedSource(source);
                        setSelectedSourceLabel(`Source ${index + 1}`);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedSource(source);
                          setSelectedSourceLabel(`Source ${index + 1}`);
                        }
                      }}
                    >
                      <span className="overline" style={{ fontSize: "0.6rem" }}>
                        {t(getLabel(source.corpus, CORPUS_LABELS))}
                      </span>
                      <h4 className="caption" style={{ fontWeight: 700 }}>
                        Source {index + 1}
                      </h4>
                      {source.source_url && (
                        <a
                          href={source.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="btn btn-secondary btn-pill"
                          style={{ padding: "4px 8px", fontSize: "0.7rem", marginTop: "4px" }}
                          onClick={(event) => event.stopPropagation()}
                        >
                          {t("Mở liên kết gốc")}
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      ) : null}
      <SourceDetailsModal source={selectedSource} sourceLabel={selectedSourceLabel} onClose={() => setSelectedSource(null)} />
    </div>
  );
}
export default SharedConversation;
