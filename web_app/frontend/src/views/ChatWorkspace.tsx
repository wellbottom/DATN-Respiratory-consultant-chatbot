import React, { useState, useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth, useUser } from "@clerk/react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Icons
import {
  MessageSquare,
  Users,
  Lock,
  Globe,
  Trash2,
  Plus,
  Send,
  Menu,
  X,
  ShieldCheck,
  Copy,
  ExternalLink,
  ChevronRight,
  Sparkles,
  Info
} from "lucide-react";

import { API_BASE, requestJson } from "../utils/api";
import { SourceDetailsModal } from "../components/SourceDetailsModal";
import {
  ConversationSummary,
  ConversationMessage,
  ConversationDetail,
  MessageResponse,
  RouteDebug,
  SourceSection,
  INTENT_LABELS,
  CORPUS_LABELS,
  COLLECTION_LABELS,
  SECTION_TYPE_LABELS,
  getLabel
} from "../types";
import { useLang } from "../i18n";

export function ChatWorkspace() {
  const { getToken, isLoaded: isAuthLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useLang();

  const userName = user?.firstName || user?.username || "phụ huynh";

  // Local Storage Key based on User
  const localStorageKey = user ? `healthylung-active-conversation:${user.id}` : "healthylung-active-conversation-public";

  // Navigation state / incoming draft prefill
  const incomingDraft = location.state?.draft || "";

  // Core States
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [conversationDetail, setConversationDetail] = useState<ConversationDetail | null>(null);
  const [composerText, setComposerText] = useState("");
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Selected Assistant message ID driving the inspector
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [inspectorRoute, setInspectorRoute] = useState<RouteDebug | null>(null);
  const [inspectorSources, setInspectorSources] = useState<SourceSection[]>([]);
  const [selectedSource, setSelectedSource] = useState<SourceSection | null>(null);
  const [selectedSourceLabel, setSelectedSourceLabel] = useState("");
  const [inspectorIsPublic, setInspectorIsPublic] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState(false);

  // Mobile Drawers
  const [isHistoryDrawerOpen, setIsHistoryDrawerOpen] = useState(false);
  const [isInspectorDrawerOpen, setIsInspectorDrawerOpen] = useState(false);

  // Auto Scroll & sizing
  const threadEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  // Get Auth Token Helper
  const getAuthToken = async (): Promise<string | null> => {
    if (!isAuthLoaded || !isSignedIn) {
      return null;
    }

    try {
      const token = await getToken();
      return token;
    } catch {
      return null;
    }
  };

  const getRequiredAuthToken = async (): Promise<string> => {
    const token = await getAuthToken();
    if (!token) {
      throw new Error("AUTH_TOKEN_UNAVAILABLE");
    }
    return token;
  };

  // Load Conversation List
  const fetchConversations = async (selectFirst = false, forceSelectId: string | null = null) => {
    setIsLoadingList(true);
    setErrorMessage(null);
    try {
      const token = await getRequiredAuthToken();
      const list: ConversationSummary[] = await requestJson(API_BASE, "/api/conversations", { token });
      setConversations(list);

      if (forceSelectId) {
        setActiveConversationId(forceSelectId);
      } else if (selectFirst && list.length > 0) {
        // Retrieve dynamic active conversation from localStorage
        const cachedId = localStorage.getItem(localStorageKey);
        const exists = list.some((c) => c.id === cachedId);
        if (cachedId && exists) {
          setActiveConversationId(cachedId);
        } else {
          setActiveConversationId(list[0].id);
        }
      }
    } catch (e: any) {
      if (e?.message === "AUTH_TOKEN_UNAVAILABLE") {
        return;
      }
      console.error("Failed to load clinical conversations list", e);
      setErrorMessage(t("Không thể tải danh sách cuộc trò chuyện. Hãy thử lại."));
    } finally {
      setIsLoadingList(false);
    }
  };

  // On Mount Load List and select first
  useEffect(() => {
    if (!isAuthLoaded) {
      return;
    }

    if (isSignedIn && user) {
      fetchConversations(true);
      return;
    }

    setConversations([]);
    setActiveConversationId(null);
    setConversationDetail(null);
    setErrorMessage(null);
  }, [isAuthLoaded, isSignedIn, user]);

  // Read incoming navigation drafts
  useEffect(() => {
    if (incomingDraft) {
      setComposerText(incomingDraft);
      // Clean location state to avoid repeating on refresh
      window.history.replaceState({}, document.title);
    }
  }, [incomingDraft]);

  // Load Individual Conversation Detail
  const loadConversationDetail = async (id: string) => {
    setIsLoadingDetail(true);
    setErrorMessage(null);
    try {
      const token = await getRequiredAuthToken();
      const detail: ConversationDetail = await requestJson(API_BASE, `/api/conversations/${id}`, { token });
      setConversationDetail(detail);
      localStorage.setItem(localStorageKey, id);

      // Find last assistant message to populate Source Inspector by default
      const assistantMessages = detail.messages.filter((m) => m.role === "assistant");
      if (assistantMessages.length > 0) {
        const lastAssistantMsg = assistantMessages[assistantMessages.length - 1];
        setSelectedMessageId(lastAssistantMsg.id);
        setInspectorRoute(lastAssistantMsg.route || null);
        setInspectorSources(lastAssistantMsg.sources || []);
      } else {
        setSelectedMessageId(null);
        setInspectorRoute(null);
        setInspectorSources([]);
      }
      setInspectorIsPublic(detail.is_public);
    } catch (e: any) {
      console.error("Failed to load details for conversation id " + id, e);
      setErrorMessage(t("Không thể tìm thấy hoặc tải chi tiết cuộc trò chuyện. Hãy thử lại."));
    } finally {
      setIsLoadingDetail(false);
    }
  };

  // Trigger Detail Loading when active ID changes
  useEffect(() => {
    if (activeConversationId) {
      loadConversationDetail(activeConversationId);
    } else {
      setConversationDetail(null);
      setSelectedMessageId(null);
      setInspectorRoute(null);
      setInspectorSources([]);
    }
  }, [activeConversationId]);

  // Clear to new Chat
  const handleNewChat = () => {
    setActiveConversationId(null);
    setConversationDetail(null);
    setSelectedMessageId(null);
    setInspectorRoute(null);
    setInspectorSources([]);
    setComposerText("");
    setIsHistoryDrawerOpen(false);
    if (composerRef.current) {
      composerRef.current.focus();
    }
  };

  // Auto Scrolling thread
  useEffect(() => {
    if (threadEndRef.current) {
      threadEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [conversationDetail?.messages, isSending]);

  // Auto Grow Texarea helper
  const handleComposerChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setComposerText(e.target.value);
    if (composerRef.current) {
      composerRef.current.style.height = "auto";
      composerRef.current.style.height = `${Math.min(composerRef.current.scrollHeight, 140)}px`;
    }
  };

  // Select Assistant Message to drive Source Inspector
  const handleSelectMessage = (msg: ConversationMessage) => {
    if (msg.role === "assistant") {
      setSelectedMessageId(msg.id);
      setInspectorRoute(msg.route || null);
      setInspectorSources(msg.sources || []);
    }
  };

  const handleUseSuggestion = (text: string) => {
    setComposerText(text);
    requestAnimationFrame(() => {
      if (!composerRef.current) return;
      composerRef.current.focus();
      composerRef.current.style.height = "auto";
      composerRef.current.style.height = `${Math.min(composerRef.current.scrollHeight, 140)}px`;
    });
  };

  // Handle Send logic (Optimistic update pattern!)
  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isSending || !composerText.trim()) return;

    const draftMessageText = composerText;
    setComposerText("");
    if (composerRef.current) {
      composerRef.current.style.height = "auto";
    }
    setIsSending(true);
    setErrorMessage(null);

    // Build optimistic structures
    const tempUserMsgId = `temp-user-${Date.now()}`;
    const tempAssistantMsgId = `temp-assistant-${Date.now()}`;

    const tempUserMsg: ConversationMessage = {
      id: tempUserMsgId,
      role: "user",
      content: draftMessageText,
      created_at: new Date().toISOString()
    };

    const tempAssistantMsg: ConversationMessage = {
      id: tempAssistantMsgId,
      role: "assistant",
      content: t("HealthyLung đang tra cứu nguồn liên quan và soạn phản hồi cho bạn..."),
      created_at: new Date().toISOString()
    };

    // Store original conversation reference for rollback option
    const originalDetail = conversationDetail;

    if (activeConversationId) {
      // Optimistic append inside existing thread
      const optimisticMessages = [
        ...(conversationDetail?.messages || []),
        tempUserMsg,
        tempAssistantMsg
      ];
      setConversationDetail((prev) =>
        prev
          ? {
              ...prev,
              messages: optimisticMessages
            }
          : null
      );
    } else {
      // Empty thread state previewing optimistic bubbles
      setConversationDetail({
        id: "temp-convo-id",
        title: t("Cuộc trò chuyện mới"),
        is_public: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        message_count: 2,
        messages: [tempUserMsg, tempAssistantMsg]
      });
    }

    try {
      const token = await getRequiredAuthToken();

      let payload: MessageResponse;
      if (activeConversationId) {
        // Send message to existing conversation
        payload = await requestJson(API_BASE, `/api/messages/${activeConversationId}`, {
          method: "POST",
          body: { message: draftMessageText },
          token
        });
      } else {
        // Send first message creating a new conversation
        payload = await requestJson(API_BASE, "/api/messages", {
          method: "POST",
          body: { message: draftMessageText },
          token
        });
      }

      // Successful API Response processing
      const responseConvo = payload.conversation;
      const userMessage = payload.user_message;
      const assistantMessage = payload.assistant_message;

      // Select newly arrived groundings for the Source Inspector
      setSelectedMessageId(assistantMessage.id);
      setInspectorRoute(assistantMessage.route || null);
      setInspectorSources(assistantMessage.sources || []);

      // If it's a new conversation, update active conversation pointer
      if (!activeConversationId) {
        setActiveConversationId(responseConvo.id);
        localStorage.setItem(localStorageKey, responseConvo.id);
        // Silently reload the thread detail and refresh total conversations
        fetchConversations(false, responseConvo.id);
      } else {
        // Update current local detail, swapping optimistic temp IDs
        setConversationDetail((prev) => {
          if (!prev) return null;
          const filtered = prev.messages.filter(
            (m) => m.id !== tempUserMsgId && m.id !== tempAssistantMsgId
          );
          return {
            ...prev,
            title: responseConvo.title,
            message_count: responseConvo.message_count,
            messages: [...filtered, userMessage, assistantMessage]
          };
        });
        // Silently sync summaries
        fetchConversations(false);
      }
    } catch (err: any) {
      console.error("Clinical response generation failed", err);
      // Restore previous draft to input and revert to the previous verified detail structure
      setComposerText(draftMessageText);
      setConversationDetail(originalDetail);
      setErrorMessage(t("Yêu cầu tư vấn thất bại. Hãy thử lại hoặc tối giản câu hỏi của bạn."));
    } finally {
      setIsSending(false);
    }
  };

  // Keyboard events trigger: Enter sends, Shift+Enter makes newline
  const handleComposerKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Put / Update sharing state parameters
  const toggleSharePublic = async () => {
    if (!activeConversationId || !conversationDetail) return;
    const targetStatus = !inspectorIsPublic;
    try {
      const token = await getRequiredAuthToken();
      const updatedSummary: ConversationSummary = await requestJson(
        API_BASE,
        `/api/conversations/${activeConversationId}`,
        {
          method: "PUT",
          body: { is_public: targetStatus },
          token
        }
      );
      setInspectorIsPublic(updatedSummary.is_public);
      setConversations((prev) =>
        prev.map((c) => (c.id === activeConversationId ? { ...c, is_public: targetStatus } : c))
      );
      setConversationDetail((prev) => (prev ? { ...prev, is_public: targetStatus } : null));
    } catch (e) {
      console.error("Failed to alter conversation sharing visibility metadata", e);
      alert(t("Cập nhật quyền truy cập liên kết thất bại."));
    }
  };

  // Copy sharing link clipboard action
  const handleCopyLink = () => {
    if (!activeConversationId) return;
    const shareUrl = `${window.location.origin}/share/${activeConversationId}`;
    navigator.clipboard.writeText(shareUrl).then(() => {
      setCopyFeedback(true);
      setTimeout(() => setCopyFeedback(false), 2000);
    });
  };

  // Confirm delete of historically stored conversations
  const handleDeleteConversation = async (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();

    const confirmed = window.confirm(t("Bạn có chắc chắn muốn xóa vĩnh viễn cuộc trò chuyện y tế này?"));
    if (!confirmed) return;

    try {
      const token = await getRequiredAuthToken();
      await fetch(`${API_BASE}/api/conversations/${id}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`
        }
      });

      // Clear pointer if active target deleted
      if (activeConversationId === id) {
        setActiveConversationId(null);
        setConversationDetail(null);
        setSelectedMessageId(null);
        setInspectorRoute(null);
        setInspectorSources([]);
        localStorage.removeItem(localStorageKey);
      }

      // Reload conversations summaries list
      fetchConversations(false);
    } catch (error) {
      console.error("Delete call request failure", error);
      alert(t("Xóa cuộc trò chuyện thất bại."));
    }
  };

  // Time localizer parsing vi-VN
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

  // Derive title monogram
  const userInitials = user?.firstName ? user.firstName.substring(0, 2).toUpperCase() : "PH";

  return (
    <div className="chat-workspace" id="chat-workspace-grid">
      {/* 1) Region LEFT Side: History Drawer Sidebar */}
      <aside className="sidebar-history" id="sidebar-conversation-history">
        {/* User Account Details Section */}
        <div className="sidebar-user-header" id="sidebar-clerk-user">
          <div
            className="avatar-circle"
            style={{ backgroundColor: "var(--brand-600)" }}
            id="avatar-user-badge"
          >
            {userInitials}
          </div>
          <div className="avatar-user-info" id="user-display-details">
            <span className="avatar-user-name">{user?.fullName || t("Cha mẹ HealthyLung")}</span>
            <span className="avatar-user-email">
              {user?.primaryEmailAddress?.emailAddress || "vietnamese@parent.com"}
            </span>
          </div>
        </div>

        <div className="sidebar-action-box" id="new-chat-trigger-box">
          <button
            onClick={handleNewChat}
            className="btn btn-secondary btn-new-chat"
            id="btn-sidebar-new-thread"
          >
            <Plus style={{ width: "16px", height: "16px" }} />
            {t("Cuộc trò chuyện mới")}
          </button>
        </div>

        <div className="history-scroll" id="history-scroll-list">
          <div className="overline history-title-overline">{t("Lịch sử tư vấn")}</div>
          {isLoadingList && conversations.length === 0 ? (
            <div className="caption text-center" style={{ padding: "24px" }}>
              {t("Đang tải danh sách...")}
            </div>
          ) : conversations.length === 0 ? (
            <div className="caption text-center" style={{ padding: "32px 16px", color: "var(--ink-500)" }}>
              {t("Chưa có cuộc trò chuyện nào. Hãy gửi tin nhắn đầu tiên!")}
            </div>
          ) : (
            conversations.map((item) => {
              const isActive = item.id === activeConversationId;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveConversationId(item.id);
                    setIsHistoryDrawerOpen(false);
                  }}
                  className={`history-item-row ${isActive ? "active" : ""}`}
                  id={`convo-row-${item.id}`}
                  style={{ width: "100%", cursor: "pointer" }}
                >
                  <div className="history-item-header">
                    <span className="history-item-title" title={item.title}>
                      {item.title || t("Cuộc trò chuyện ẩn danh")}
                    </span>
                  </div>
                  <div className="history-item-meta">
                    <span className="history-item-time">{formatIsoDate(item.updated_at)}</span>
                    <div className="history-item-pills">
                      {item.is_public ? (
                        <span className="pill-sm pill-public" title={t("Bất kỳ ai có liên kết đều xem được")}>
                          {t("Mở")}
                        </span>
                      ) : (
                        <span className="pill-sm pill-private" title={t("Chỉ mình tôi xem được")}>
                          {t("Riêng tư")}
                        </span>
                      )}
                      <span className="pill-sm" style={{ backgroundColor: "var(--surface)", color: "var(--ink-500)" }}>
                        {t("{n} tin", { n: item.message_count })}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={(e) => handleDeleteConversation(e, item.id)}
                    className="btn-delete-history"
                    title={t("Xóa cuộc trò chuyện này")}
                    aria-label={t("Xóa")}
                  >
                    <Trash2 style={{ width: "14px", height: "14px" }} />
                  </button>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {/* 2) Region CENTER: Chat stream panels & floating composer */}
      <section className="chat-center-thread" id="chat-center-thread-viewport">
        {/* Mobile Controller Access Panel */}
        <div className="mobile-chat-controls-header" id="mobile-viewport-subnavigation">
          <button
            onClick={() => setIsHistoryDrawerOpen(true)}
            className="btn btn-secondary btn-pill btn-sm"
            style={{ padding: "6px 12px" }}
            id="btn-mobile-open-history"
          >
            <Menu style={{ width: "14px", height: "14px" }} />
            {t("Lịch sử")}
          </button>
          <span className="caption" style={{ fontWeight: 600 }}>
            {conversationDetail?.title || t("Trò chuyện mới")}
          </span>
          <button
            onClick={() => setIsInspectorDrawerOpen(true)}
            className="btn btn-secondary btn-pill btn-sm"
            style={{ padding: "6px 12px" }}
            id="btn-mobile-open-details"
          >
            {t("Đọc nguồn ({n})", { n: inspectorSources.length })}
          </button>
        </div>

        {errorMessage && (
          <div className="warning-banner" id="error-alert-banner" style={{ margin: "2px" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
              <Info style={{ width: "16px", height: "16px" }} />
              {errorMessage}
            </span>
          </div>
        )}

        <div className="thread-stream-container" id="stream-bubbles-flow" aria-live="polite">
          {!conversationDetail || conversationDetail.messages.length === 0 ? (
            /* Empty welcome structure */
            <div className="chat-empty-welcome" id="empty-state-welcome-panel">
              <div className="empty-welcome-emoji-ring">
                <Sparkles style={{ width: "32px", height: "32px", color: "white" }} />
              </div>
              <h2 className="h2" style={{ marginTop: "12px" }}>
                {t("Chào {userName}, tôi là HealthyLung AI!", { userName })}
              </h2>
              <p className="caption" style={{ fontSize: "0.95rem", color: "var(--ink-500)" }}>
                {t("Tôi tự động phân tích câu hỏi của bạn, truy cập khối thông tin chính thống từ Vinmec và các nguồn nhi khoa lâm sàng để tìm giải pháp chu đáo nhất. Thử đặt câu hỏi dưới đây:")}
              </p>
              <div className="empty-welcome-hint-list">
                <button
                  type="button"
                  className="empty-hint-card"
                  onClick={() => handleUseSuggestion(t("Trẻ 6 tháng tuổi sốt 38.5 độ phát ban đỏ cần chăm sóc thế nào?"))}
                >
                  📌 "{t("Trẻ 6 tháng tuổi sốt 38.5 độ phát ban đỏ cần chăm sóc thế nào?")}"
                </button>
                <button
                  type="button"
                  className="empty-hint-card"
                  onClick={() => handleUseSuggestion(t("Dấu hiệu cấp cứu khẩn cấp khi bé sơ sinh bị tiêu chảy?"))}
                >
                  📌 "{t("Dấu hiệu cấp cứu khẩn cấp khi bé sơ sinh bị tiêu chảy?")}"
                </button>
                <button
                  type="button"
                  className="empty-hint-card"
                  onClick={() => handleUseSuggestion(t("Bé biếng ăn dặm, chậm tăng cân cần bổ sung dinh dưỡng gì?"))}
                >
                  📌 "{t("Bé biếng ăn dặm, chậm tăng cân cần bổ sung dinh dưỡng gì?")}"
                </button>
              </div>
            </div>
          ) : (
            conversationDetail.messages.map((item) => {
              const isUser = item.role === "user";
              const isSelected = selectedMessageId === item.id;
              const hasIntel = item.route || (item.sources && item.sources.length > 0);

              return (
                <div
                  key={item.id}
                  className={`message-bubble-row ${isUser ? "user" : "assistant"} ${
                    isSelected ? "selected" : ""
                  }`}
                  id={`bubble-msg-wrapper-${item.id}`}
                  role={!isUser ? "button" : undefined}
                  tabIndex={!isUser ? 0 : undefined}
                  onClick={() => handleSelectMessage(item)}
                  onKeyDown={(e) => {
                    if (!isUser && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      handleSelectMessage(item);
                    }
                  }}
                >
                  <span className="bubble-meta-label">
                    {isUser ? t("Bạn") : "HealthyLung AI"} · {formatIsoDate(item.created_at)}
                    {!isUser && hasIntel && (
                      <span
                        className="pill-sm"
                        style={{
                          backgroundColor: "var(--intel-50)",
                          color: "var(--intel-500)",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "3px"
                        }}
                      >
                        <Sparkles style={{ width: "10px", height: "10px" }} /> {t("Chi tiết nguồn")}
                      </span>
                    )}
                  </span>
                  <div className="bubble-text-box">
                    {isSending && item.id.startsWith("temp-assistant-") ? (
                      <div className="thinking-shimmer" id="shimmer-calculating-loader">
                        <div className="dot"></div>
                        <div className="dot"></div>
                        <div className="dot"></div>
                        <span
                          className="caption"
                          style={{ color: "var(--brand-600)", fontWeight: 600, marginLeft: "8px" }}
                        >
                          {t("HealthyLung đang phân loại triệu chứng lâm sàng và tổng hợp tài liệu...")}
                        </span>
                      </div>
                    ) : (
                      <div className="markdown-body">
                        <Markdown remarkPlugins={[remarkGfm]}>{item.content}</Markdown>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
          <div ref={threadEndRef} />
        </div>

        {/* Floating Glass Composer Area */}
        <div className="composer-outer-anchor" id="thread-input-editor-bar">
          <form className="composer-glass-box" onSubmit={handleSendMessage} id="composer-glass-form">
            <div className="composer-input-row">
              <textarea
                ref={composerRef}
                value={composerText}
                onChange={handleComposerChange}
                onKeyDown={handleComposerKeyDown}
                placeholder={t("Ví dụ: Bé nhà mình bị ho khan kéo dài 3 ngày...")}
                className="composer-textarea"
                rows={1}
                disabled={isSending}
                id="composer-input-textarea"
              />
              <button
                type="submit"
                disabled={isSending || !composerText.trim()}
                className={`btn-composer-send ${composerText.trim() ? "armed" : ""}`}
                title={t("Gửi câu hỏi")}
                aria-label={t("Gửi")}
                id="btn-composer-send-msg"
              >
                <Send style={{ width: "16px", height: "16px" }} />
              </button>
            </div>
            <div className="composer-hint-row">
              <span>{t("Để gửi: nhấn Enter · Để xuống dòng: nhấn Shift + Enter")}</span>
              <span>{t("Dữ liệu lâm sàng tự động cập nhật liên tục")}</span>
            </div>
          </form>
        </div>
      </section>

      {/* 3) Region RIGHT Side: Source Inspector */}
      <aside className="sidebar-sources" id="sidebar-sources-inspector">
        <div className="sources-header-box" id="sources-header-bar">
          <span className="overline" style={{ color: "var(--ink-900)" }}>
            {t("Bảng Kiểm Chứng Nguồn")}
          </span>
        </div>

        <div className="sources-scroll-area" id="inspector-data-scroll">
          {inspectorRoute || inspectorSources.length > 0 ? (
            <>
              {/* Route Intent Identification */}
              {inspectorRoute && (
                <div className="route-debug-card" id="route-debug-card-view">
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span className="caption" style={{ fontWeight: 700, color: "var(--intel-500)" }}>
                      {t("Hướng Trả Lời:")} {t(getLabel(inspectorRoute.intent, INTENT_LABELS))}
                    </span>
                    <span className="intelligence-chip">AI Routing</span>
                  </div>
                  <p className="caption" style={{ fontStyle: "italic", margin: "4px 0" }}>
                    {t("Cơ sở dữ liệu y khoa đề xuất trọng tâm phân tích thuộc nhóm đặc tính:")}{" "}
                    <strong>{t(getLabel(inspectorRoute.intent, INTENT_LABELS))}</strong>.
                  </p>
                  <div className="provider-tags-flow" style={{ marginTop: "4px" }}>
                    {inspectorRoute.collection_name && (
                      <span className="pill-sm pill-public">
                        {t(getLabel(inspectorRoute.collection_name, COLLECTION_LABELS))}
                      </span>
                    )}
                    {inspectorRoute.corpora &&
                      inspectorRoute.corpora.map((corp, index) => (
                        <span key={index} className="pill-sm pill-private" style={{ fontSize: "0.65rem" }}>
                          {t(getLabel(corp, CORPUS_LABELS))}
                        </span>
                      ))}
                  </div>

                  {inspectorRoute.reasons && inspectorRoute.reasons.length > 0 && (
                    <div style={{ marginTop: "8px" }}>
                      <span className="overline" style={{ fontSize: "0.65rem", display: "block" }}>
                        {t("Cơ sở phân loại")}
                      </span>
                      <ul className="intel-reasons-list">
                        {inspectorRoute.reasons.map((reason, idx) => (
                          <li key={idx}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Safety Warning Panel */}
              <div className="safety-warning-card" id="safety-disclaimer-card">
                <div className="safety-header-label">
                  <ShieldCheck style={{ color: "var(--danger)" }} />
                  {t("Cảnh báo Y tế Lâm sàng")}
                </div>
                <div className="safety-bullet-list">
                  <div className="safety-bullet">
                    {t("Thông tin từ HealthyLung AI chỉ mang tính chất tham khảo, không thay thế cho chẩn đoán chuyên môn của bác sĩ.")}
                  </div>
                  <div className="safety-bullet">
                    <strong>{t("Đỏ khẩn cấp:")}</strong> {t("Nếu trẻ xuất hiện co giật, li bì, khó thở rít, mất nước nặng, hãy gọi ngay cấp cứu hoặc tới bệnh viện nhi khoa gần nhất.")}
                  </div>
                  <div className="safety-bullet">
                    {t("Đối chiếu kỹ nội dung các bài viết của y sĩ chuyên khoa trước khi tự áp dụng tại nhà.")}
                  </div>
                </div>
              </div>

              {/* Share Control Management (only for active valid conversations) */}
              {activeConversationId && (
                <div className="sharing-status-card" id="inspector-sharing-controls">
                  <div className="sharing-status-top">
                    <span className="caption" style={{ fontWeight: 700 }}>
                      {t("Liên kết chia sẻ công khai")}
                    </span>
                    {inspectorIsPublic ? (
                      <span className="badge-location-status acquired">{t("Công khai")}</span>
                    ) : (
                      <span className="badge-location-status pending" style={{ color: "var(--ink-500)", backgroundColor: "var(--surface-2)" }}>
                        {t("Riêng tư")}
                      </span>
                    )}
                  </div>

                  <p className="caption" style={{ fontSize: "0.8125rem" }}>
                    {t("Bật chế độ công khai để lưu lại đường dẫn chia sẻ bài tư vấn này cho người thân.")}
                  </p>

                  <div style={{ display: "flex", gap: "8px" }}>
                    <button
                      onClick={toggleSharePublic}
                      className="btn btn-secondary btn-pill"
                      style={{ flex: 1, padding: "8px 12px", fontSize: "0.8125rem" }}
                    >
                      {inspectorIsPublic ? t("Hủy chia sẻ công khai") : t("Kích hoạt chia sẻ")}
                    </button>
                    <button
                      onClick={handleCopyLink}
                      disabled={!inspectorIsPublic}
                      className="btn btn-primary btn-pill"
                      style={{ padding: "8px 12px", fontSize: "0.8125rem" }}
                      title={t("Sao chép liên kết")}
                    >
                      {copyFeedback ? t("Đã sao chép!") : <Copy style={{ width: "14px", height: "14px" }} />}
                    </button>
                  </div>

                  {inspectorIsPublic && (
                    <div className="mono-url-display">
                      {window.location.origin}/share/{activeConversationId}
                    </div>
                  )}
                </div>
              )}

              {/* List of Retrieved Sources */}
              {inspectorSources.length > 0 && (
                <div id="sources-mapped-list">
                  <span className="overline" style={{ display: "block", marginBottom: "12px" }}>
                    {t("Nguồn tham chiếu y khoa ({n})", { n: inspectorSources.length })}
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    {inspectorSources.map((source, idx) => {
                      const sourceLabel = `Source ${idx + 1}`;

                      return (
                        <div
                          key={idx}
                          className="source-section-card source-section-card-clickable"
                          id={`source-idx-${idx}`}
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
                            <span className="overline" style={{ fontSize: "0.6875rem", color: "var(--brand-600)" }}>
                              {t(getLabel(source.corpus, CORPUS_LABELS))}
                            </span>
                          </div>

                          <h4 className="caption" style={{ fontWeight: 700, color: "var(--ink-900)", lineHeight: 1.3 }}>
                            {sourceLabel}
                          </h4>

                          {source.h2 && (
                            <div className="source-breadcrumb-row" style={{ fontSize: "0.75rem" }}>
                              ↳ {source.h2} {source.h3 ? `> ${source.h3}` : ""}
                            </div>
                          )}

                          <div className="provider-tags-flow" style={{ marginTop: "4px" }}>
                            <span className="pill-sm" style={{ backgroundColor: "var(--surface-2)", color: "var(--ink-700)" }}>
                              {t(getLabel(source.section_type, SECTION_TYPE_LABELS))}
                            </span>
                            <span className="pill-sm" style={{ backgroundColor: "var(--surface-2)", color: "var(--ink-500)" }}>
                              {t("{n} đoạn trích", { n: source.chunk_count })}
                            </span>
                          </div>

                          {source.source_url ? (
                            <a
                              href={source.source_url}
                              target="_blank"
                              referrerPolicy="no-referrer"
                              rel="noreferrer"
                              className="btn btn-secondary btn-pill"
                              style={{
                                padding: "4px 8px",
                                fontSize: "0.75rem",
                                marginTop: "6px",
                                width: "100%",
                                display: "inline-flex",
                                justifyContent: "center"
                              }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLink style={{ width: "12px", height: "12px" }} />
                              {source.source_url_kind === "search" ? t("Tìm bái trên Vinmec") : t("Mở bài gốc từ sở y tế")}
                            </a>
                          ) : (
                            <span className="caption" style={{ fontSize: "0.75rem", marginTop: "4px", fontStyle: "italic", display: "inline-block" }}>
                              {t("Tài liệu nội bộ được bảo vệ bản quyền.")}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="sources-empty-state" id="sources-view-empty">
              <MessageSquare />
              <span className="caption">
                {t("Chọn tin nhắn câu trả lời của ")}<strong style={{ color: "var(--brand-600)" }}>HealthyLung AI</strong>{t(" để tra cứu chi tiết nguồn tài liệu lâm sàng tham khảo.")}
              </span>
            </div>
          )}
        </div>
      </aside>

      {/* 4) OVERLAYS: Responsive History slide-over drawer on mobile */}
      {isHistoryDrawerOpen && (
        <div className="drawer-scrim" onClick={() => setIsHistoryDrawerOpen(false)}>
          <div
            className="drawer-slide-content left"
            id="mobile-drawer-left-history"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-header">
              <span className="overline" style={{ color: "var(--ink-900)" }}>
                {t("Lịch sử cuộc gọi")}
              </span>
              <button onClick={() => setIsHistoryDrawerOpen(false)} aria-label={t("Đóng")}>
                <X />
              </button>
            </div>
            <div className="drawer-body-scroll">
              <div className="sidebar-action-box">
                <button
                  onClick={handleNewChat}
                  className="btn btn-secondary btn-new-chat"
                >
                  <Plus style={{ width: "16px", height: "16px" }} />
                  {t("Bắt đầu trò chuyện mới")}
                </button>
              </div>
              <div style={{ padding: "0 12px" }}>
                {conversations.map((item) => {
                  const isActive = item.id === activeConversationId;
                  return (
                    <button
                      key={item.id}
                      onClick={() => {
                        setActiveConversationId(item.id);
                        setIsHistoryDrawerOpen(false);
                      }}
                      className={`history-item-row ${isActive ? "active" : ""}`}
                      style={{ width: "100%", margin: "6px 0" }}
                    >
                      <span className="history-item-title">{item.title}</span>
                      <div className="history-item-meta">
                        <span className="history-item-time">{formatIsoDate(item.updated_at)}</span>
                        <span className="pill-sm pill-public">{t("{n} tin", { n: item.message_count })}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 5) OVERLAYS: Responsive Inspector slide-over drawer on mobile */}
      {isInspectorDrawerOpen && (
        <div className="drawer-scrim" onClick={() => setIsInspectorDrawerOpen(false)}>
          <div
            className="drawer-slide-content right"
            id="mobile-drawer-right-sources"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-header">
              <span className="overline" style={{ color: "var(--ink-900)" }}>
                {t("Kiểm chứng thông tin")}
              </span>
              <button onClick={() => setIsInspectorDrawerOpen(false)} aria-label={t("Đóng")}>
                <X />
              </button>
            </div>
            <div className="drawer-body-scroll" style={{ padding: "16px" }}>
              {inspectorRoute || inspectorSources.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  {inspectorRoute && (
                    <div className="route-debug-card">
                      <span className="caption" style={{ fontWeight: 700, color: "var(--intel-500)" }}>
                        {t("Hướng:")} {t(getLabel(inspectorRoute.intent, INTENT_LABELS))}
                      </span>
                      <div className="provider-tags-flow">
                        {inspectorRoute.collection_name && (
                          <span className="pill-sm pill-public">
                            {t(getLabel(inspectorRoute.collection_name, COLLECTION_LABELS))}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="safety-warning-card">
                    <span className="safety-header-label">{t("Cảnh báo")}</span>
                    <span className="caption" style={{ fontSize: "0.8rem" }}>
                      {t("Nội dung chỉ tham khảo. Gọi cấp cứu y tế nếu bé gặp biểu hiện thở rít, li bì, co giật.")}
                    </span>
                  </div>

                  {inspectorSources.map((source, index) => (
                    <div
                      key={index}
                      className="source-section-card source-section-card-clickable"
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
                      <p className="caption" style={{ fontSize: "0.75rem" }}>
                        {source.h2 ? `↳ ${source.h2}` : ""}
                      </p>
                      {source.source_url && (
                        <a
                          href={source.source_url}
                          target="_blank"
                          referrerPolicy="no-referrer"
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
              ) : (
                <div className="sources-empty-state">
                  <MessageSquare />
                  <span className="caption">{t("Nhấn vào bong bóng câu trả lời ở luồng để đọc nguồn gốc y văn.")}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      <SourceDetailsModal source={selectedSource} sourceLabel={selectedSourceLabel} onClose={() => setSelectedSource(null)} />
    </div>
  );
}
export default ChatWorkspace;
