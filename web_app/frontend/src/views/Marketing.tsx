import { SignInButton, SignUpButton } from "@clerk/react";
import { Sparkles, ShieldCheck, Stethoscope } from "lucide-react";
import { LangToggle, useLang } from "../i18n";

interface MarketingProps {
  clerkEnabled: boolean;
}

export function Marketing({ clerkEnabled }: MarketingProps) {
  const { t } = useLang();
  return (
    <div className="marketing-hero" id="marketing-viewport">
      {/* Decorative gradient canvas blobs */}
      <div className="marketing-blob"></div>
      <div className="marketing-blob-2"></div>

      <div style={{ position: "absolute", top: "20px", right: "20px", zIndex: 2 }}>
        <LangToggle />
      </div>

      <div className="marketing-card" id="marketing-card-panel">
        {!clerkEnabled && (
          <div className="warning-banner" id="clerk-disabled-warning-banner">
            {t("⚠️ Chế độ dùng thử (Cấu hình xác thực Clerk từ xa hiện chưa sẵn sàng)")}
          </div>
        )}

        <div className="marketing-icon-wrapper" id="brand-spark-launcher">
          <Sparkles />
        </div>

        <h1 className="display-xl marketing-title" id="marketing-hero-heading">
          HealthyLung
        </h1>
        <p className="marketing-subtitle" id="marketing-hero-subheading">
          {t("Trợ lý sức khỏe nhi khoa thông minh dựa trên trí tuệ nhân tạo. Tra cứu chính xác nguồn tham chiếu, bảo bối đắc lực cho cha mẹ trong việc chăm sóc và theo dõi sức khỏe của bé yêu, đáng tin cậy kể cả lúc 3 giờ sáng.")}
        </p>

        <div className="marketing-ctas" id="marketing-ctas-container">
          <SignInButton mode="modal">
            <button className="btn btn-primary btn-pill" id="action-signin-primary">
              {t("Bắt đầu trò chuyện")}
            </button>
          </SignInButton>
          <SignUpButton mode="modal">
            <button className="btn btn-secondary btn-pill" id="action-signup-secondary">
              {t("Tạo tài khoản mới")}
            </button>
          </SignUpButton>
        </div>

        <div className="marketing-trust" id="trust-indicator-row">
          <div className="trust-item" id="trust-check-1">
            <ShieldCheck />
            <span>{t("Nguồn tài liệu chính thống, cập nhật mới nhất")}</span>
          </div>
          <div className="trust-item" id="trust-check-2">
            <Stethoscope />
            <span>{t("Trải nghiệm mượt mà")}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
