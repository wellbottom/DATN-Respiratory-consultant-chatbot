import { Link, useNavigate } from "react-router-dom";
import { useUser } from "@clerk/react";
import { MessageSquare, Users, MapPin, Sparkles, ChevronRight } from "lucide-react";
import { useLang } from "../i18n";

export function HomeHub() {
  const { user } = useUser();
  const navigate = useNavigate();
  const { t } = useLang();

  const userName = user?.firstName || user?.username || "phụ huynh";

  return (
    <div className="main-container-limited home-hub" id="home-hub-page">
      {/* Personalized Welcome Banner */}
      <section className="welcome-panel" id="personalized-welcome-banner">
        <div className="hub-aurora-accent"></div>
        <div className="welcome-content">
          <div className="overline" style={{ color: "var(--brand-600)" }}>
            {t("Bắt đầu chăm sóc con yêu tốt hơn")}
          </div>
          <h2 className="display-xl" id="greeting-username" style={{ fontSize: "2.25rem", margin: "4px 0" }}>
            {t("Xin chào, {userName}! 👋", { userName })}
          </h2>
          <p className="welcome-tagline" id="home-hub-tagline">
            {t("HealthyLung đồng hành cùng bạn chăm sóc sức khỏe cho bé từ 0 - 12 tuổi. Hãy hỏi tôi về triệu chứng, liều lượng vắc-xin, chế độ dinh dưỡng hoặc tìm phòng khám nhi và trường học gần nhất.")}
          </p>
          <div className="welcome-actions" id="welcome-fast-actions">
            <button onClick={() => navigate("/chat")} className="btn btn-primary" id="btn-welcome-chat">
              <MessageSquare style={{ width: "18px", height: "18px" }} />
              {t("Bắt đầu trò chuyện mới")}
            </button>
            <button onClick={() => navigate("/community")} className="btn btn-secondary" id="btn-welcome-community">
              <Users style={{ width: "18px", height: "18px" }} />
              {t("Góc chia sẻ từ cha mẹ khác")}
            </button>
          </div>
        </div>
      </section>

      {/* 3 Clickable Feature Cards (Bento Style) */}
      <section className="preview-grid" id="features-bento-layout" aria-label={t("Các tính năng chính")}>
        <Link to="/chat" className="preview-card" id="chat-feature-card">
          <div className="card-icon-box brand-color">
            <MessageSquare />
          </div>
          <div>
            <h3 className="preview-card-title">
              {t("Tư vấn Sức khỏe AI")}
              <ChevronRight className="arrow-in-card" />
            </h3>
            <p className="preview-card-desc">
              {t("Hỏi đáp triệu chứng, chẩn đoán sơ bộ, điều trị và chăm sóc bé tại nhà. Câu trả lời chính xác, được kiểm chứng dựa trên thông tin y khoa của hệ thống đa nguồn.")}
            </p>
          </div>
        </Link>

        <Link to="/community" className="preview-card" id="community-feature-card">
          <div className="card-icon-box accent-color">
            <Users />
          </div>
          <div>
            <h3 className="preview-card-title">
              {t("Cộng đồng Chia sẻ")}
              <ChevronRight className="arrow-in-card" />
            </h3>
            <p className="preview-card-desc">
              {t("Xem các thắc mắc phổ biến, tâm sự và kinh nghiệm của các cha mẹ Việt khác. Bạn có thể sử dụng lại câu hỏi thảo luận chỉ với đúng một nhấp chuột tiện lợi.")}
            </p>
          </div>
        </Link>

        <Link to="/find-care" className="preview-card" id="findcare-feature-card">
          <div className="card-icon-box intel-color">
            <MapPin />
          </div>
          <div>
            <h3 className="preview-card-title">
              {t("Tìm nơi Y tế & Giữ trẻ")}
              <ChevronRight className="arrow-in-card" />
            </h3>
            <p className="preview-card-desc">
              {t("Xác định vị trí tự động hoặc thủ công để tìm các bệnh viện nhi, phòng khám đa khoa chất lượng, nhà trẻ, trường mầm non và dịch vụ bảo mẫu xung quanh bạn.")}
            </p>
          </div>
        </Link>
      </section>
    </div>
  );
}
