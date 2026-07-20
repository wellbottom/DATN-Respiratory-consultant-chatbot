import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageSquare, Plus, Heart, MessageCircle, Sparkles, Send } from "lucide-react";
import { useLang } from "../i18n";

interface SharedPost {
  id: string;
  author: string;
  role: string;
  avatarChar: string;
  avatarColor: string;
  time: string;
  topic: string;
  topicTag: string;
  userSnippet: string;
  assistantSnippet: string;
  likes: number;
  comments: number;
  savedDraft: string;
}

const SEED_POSTS: SharedPost[] = [
  {
    id: "post-1",
    author: "Thu Trang Ngô",
    role: "Mẹ bé Thỏ (14 tháng)",
    avatarChar: "TT",
    avatarColor: "#FF7A4D",
    time: "2 giờ trước",
    topic: "symptom",
    topicTag: "Sốt mọc răng",
    userSnippet: "Bé nhà em 14 tháng tuổi bị sốt 38.6 độ, sưng nướu răng lợi đỏ tấy, quấy khóc cả đêm không chịu ăn bún cháo gì...",
    assistantSnippet: "Theo cẩm nang nhi khoa Vinmec, sốt mọc răng ở mức dưới 38.5°C khuyên dùng khăn ấm lau bẹn nách. Tránh gãi nướu và có thể bổ sung sữa mát...",
    likes: 18,
    comments: 4,
    savedDraft: "Bé nhà em 14 tháng tuổi bị sốt 38.6 độ kèm theo sưng đỏ lợi sưng nướu quấy khóc mọc răng, xử lý thế nào ạ?"
  },
  {
    id: "post-2",
    author: "Linh Nguyễn",
    role: "Bố bé Sóc (8 tháng)",
    avatarChar: "LN",
    avatarColor: "#0E9E8C",
    time: "Hôm qua",
    topic: "treatment",
    topicTag: "Chế độ ăn dặm",
    userSnippet: "Hỏi hành trình ăn dặm tự chỉ huy cho bé 8 tháng biếng ăn, chậm tăng cân, lười uống nước lọc thì cải thiện thế nào?",
    assistantSnippet: "Phương pháp BLW khuyên duy trì sữa mẹ tối thiểu 700ml/ngày ở tháng thứ 8. Tạo phản xạ nhai bằng rau củ hấp chín mềm cắt thanh dài...",
    likes: 31,
    comments: 11,
    savedDraft: "Hành trình ăn dặm tự chỉ huy cho bé 8 tháng chậm tăng cân, lười uống nước lọc cần lưu ý những gì?"
  },
  {
    id: "post-3",
    author: "Phan Ánh Dương",
    role: "Mẹ bé Muối (3 tháng)",
    avatarChar: "AD",
    avatarColor: "#7C6CF0",
    time: "3 ngày trước",
    topic: "general",
    topicTag: "Trẻ sơ sinh",
    userSnippet: "Trẻ sơ sinh rụng rốn muộn (đã 22 ngày tuổi) nhưng không rỉ dịch mủ rỉ vàng có cần đi phòng khám khám không?",
    assistantSnippet: "Thời điểm rụng rốn trung bình là 7-15 ngày. Nếu rốn khô sạch không đỏ xung quanh hay không chảy máu thì có thể theo dõi thêm tại nhà. Không bôi thuốc lạ...",
    likes: 12,
    comments: 2,
    savedDraft: "Trẻ sơ sinh 22 ngày tuổi chưa rụng rốn nhưng rốn khô ráo không hôi nách không đỏ tấy thì có bình thường không?"
  },
  {
    id: "post-4",
    author: "Nguyễn Hải Đăng",
    role: "Bố bé Cà Rốt (2 tuổi)",
    avatarChar: "HĐ",
    avatarColor: "#0284C7",
    time: "4 ngày trước",
    topic: "prevention",
    topicTag: "Lịch tiêm phòng vắc-xin",
    userSnippet: "Hạn tiêm vắc xin phế cầu Synflorix muộn so với phác đồ chuẩn ở bé 2 tuổi thì có bị mất tác dụng phòng ngừa phế cầu không?",
    assistantSnippet: "Vắc-xin tiêm muộn vẫn duy trì được hiệu quả kích thích miễn dịch, không cần tiêm lại từ đầu, tuy nhiên khoảng thời gian trễ khiến bé có nguy cơ nhiễm trùng...",
    likes: 22,
    comments: 6,
    savedDraft: "Bé 2 tuổi tiêm vắc-xin phế cầu Synflorix bị trễ phác đồ tiêm chủng chuẩn thì có cần tiêm lại từ đầu không?"
  }
];

export function Community() {
  const navigate = useNavigate();
  const { t } = useLang();
  const [selectedTopic, setSelectedTopic] = useState<string>("all");

  const filteredPosts =
    selectedTopic === "all" ? SEED_POSTS : SEED_POSTS.filter((post) => post.topic === selectedTopic);

  // Trigger prompt reuse and transition to Workspace Chat
  const handleReuseQuestion = (draft: string) => {
    navigate("/chat", { state: { draft } });
  };

  const topicChips = [
    { key: "all", label: t("Tất cả chủ đề") },
    { key: "symptom", label: t("Triệu chứng & sốt") },
    { key: "treatment", label: t("Dinh dưỡng & ăn dặm") },
    { key: "general", label: t("Trẻ sơ sinh") },
    { key: "prevention", label: t("Vắc-xin & Phòng ngừa") }
  ];

  return (
    <div className="main-container-limited" id="community-hub-page">
      {/* Page Header */}
      <div className="community-header" id="community-main-header">
        <div>
          <span className="overline" style={{ color: "var(--brand-600)" }}>{t("Góc chia sẻ kinh nghiệm")}</span>
          <h1 className="h1" style={{ marginTop: "4px" }}>{t("Diễn đàn Cha Mẹ HealthyLung")}</h1>
          <p className="caption" style={{ fontSize: "0.95rem", color: "var(--ink-500)", marginTop: "4px" }}>
            {t("Nơi tổng hợp các nội dung tư vấn y khoa công khai, bổ ích được lưu trữ từ cộng đồng các ông bố bà mẹ bỉm sữa Việt.")}
          </p>
        </div>
        <button onClick={() => navigate("/chat")} className="btn btn-primary btn-pill" id="action-community-to-chat">
          <Plus style={{ width: "16px", height: "16px" }} />
          {t("Mở cuộc tư vấn mới")}
        </button>
      </div>

      {/* Topics Filtering */}
      <div className="filter-chips-row" id="topic-filters-container">
        {topicChips.map((chip) => (
          <button
            key={chip.key}
            onClick={() => setSelectedTopic(chip.key)}
            className={`chip ${selectedTopic === chip.key ? "active" : ""}`}
            id={`filter-chip-${chip.key}`}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* Grid of Shared Stories */}
      <section className="community-feed-grid" id="community-posts-list" aria-label={t("Danh sách chia sẻ cộng đồng")}>
        {filteredPosts.map((post) => (
          <article className="community-post-card" key={post.id} id={`post-card-${post.id}`}>
            {/* Author details */}
            <div className="post-author-header">
              <div className="post-author-info">
                <div
                  className="avatar-circle"
                  style={{ backgroundColor: post.avatarColor, width: "38px", height: "38px", fontSize: "0.8rem" }}
                >
                  {post.avatarChar}
                </div>
                <div className="avatar-user-info">
                  <span className="avatar-user-name" style={{ fontSize: "0.9rem" }}>{post.author}</span>
                  <span className="caption" style={{ fontSize: "0.75rem" }}>{post.role} · {post.time}</span>
                </div>
              </div>
              <span className="post-topic-tag">{post.topicTag}</span>
            </div>

            {/* Conversation Dialog Box Snippet */}
            <div className="post-body-snippet" id={`snippet-box-${post.id}`}>
              <div className="snippet-line user">
                💬 <strong style={{ color: "var(--ink-900)" }}>{t("Hỏi:")}</strong> "{post.userSnippet}"
              </div>
              <div className="snippet-line assistant">
                <span className="overline" style={{ fontSize: "0.65rem", display: "block", color: "var(--brand-600)", fontWeight: 700, marginBottom: "4px" }}>
                  <Sparkles style={{ width: "10px", height: "10px", display: "inline-block", marginRight: "3px" }} />
                  {t("HealthyLung AI tư vấn (Dựa trên tài liệu kiểm chứng)")}
                </span>
                "...{post.assistantSnippet}..."
              </div>
            </div>

            {/* Engagement Row and Reuse action */}
            <div className="post-engagement-bar">
              <div className="post-likes-comments">
                <div className="engagement-item" title={t("Cảm ơn")}>
                  <Heart style={{ width: "15px", height: "15px", fill: "rgba(225, 29, 72, 0.1)", color: "var(--danger)" }} />
                  <span>{post.likes}</span>
                </div>
                <div className="engagement-item" title={t("Thảo luận")}>
                  <MessageCircle style={{ width: "15px", height: "15px", color: "var(--ink-500)" }} />
                  <span>{t("{n} bình luận", { n: post.comments })}</span>
                </div>
              </div>
              <button
                onClick={() => handleReuseQuestion(post.savedDraft)}
                className="btn btn-accent btn-pill btn-sm"
                style={{ padding: "6px 12px", fontSize: "0.8rem" }}
                id={`btn-reuse-${post.id}`}
              >
                <Send style={{ width: "12px", height: "12px" }} />
                {t("Dùng lại câu hỏi")}
              </button>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
export default Community;
