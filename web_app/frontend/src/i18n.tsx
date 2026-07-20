import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Languages } from "lucide-react";

export type Lang = "vi" | "en";

const STORAGE_KEY = "healthylung-lang";

// ponytail: gettext-style i18n. The Vietnamese source string IS the key, so vi
// is the default and never needs a lookup. Only an English override map is kept
// below. Ceiling: dynamic content (AI chat messages, seeded demo posts, mock
// facility data) and any text sent to the AI are intentionally NOT translated —
// switching language only swaps static UI chrome. Upgrade path: add entries to
// EN or move to a full ICU/i18next setup if pluralization/locale data grows.
const EN: Record<string, string> = {
  // App.tsx boot / config screens
  "Không thể kết nối với máy chủ quản lý cấu hình HealthyLung. Vui lòng kiểm tra lại dịch vụ mạng.":
    "Could not connect to the HealthyLung configuration server. Please check your network connection.",
  "Đang tải dữ liệu chăm sóc lâm sàng...": "Loading clinical care data...",
  "Lỗi kết nối máy chủ": "Server connection error",
  "Thử kết nối lại": "Retry connection",
  "Thiếu cấu hình đăng nhập (Clerk)": "Missing login configuration (Clerk)",
  "Cuộc trò chuyện này yêu cầu tài khoản người dùng bỉm sữa được xác thực bằng hệ thống ":
    "This conversation requires a parent account authenticated via ",
  ". Tuy nhiên, khóa công khai ": ". However, the publishable key ",
  " chưa được thiết lập từ xa trên máy chủ HealthyLung.":
    " has not been set remotely on the HealthyLung server.",
  "Hướng dẫn cấu hình dành cho nhà phát triển:": "Configuration guide for developers:",
  "1. Thiết lập biến môi trường ": "1. Set the environment variable ",
  " trong cài đặt bí mật hoặc file ": " in your secrets or the ",
  "2. Đảm bảo dịch vụ ": "2. Make sure the ",
  " trả về giá trị ": " value returns ",
  " trên API cấu hình của bạn.": " from your config API.",
  "Bạn vẫn có thể kiểm tra một đường liên kết chia sẻ công khai mẫu:":
    "You can still test a sample public share link:",
  "Xem cuộc trò chuyện chia sẻ mẫu": "View sample shared conversation",

  // AppShell nav
  "Trang chủ": "Home",
  "Trò chuyện": "Chat",
  "Cộng đồng": "Community",
  "Bản đồ Nhi": "Pediatric Map",
  "Tìm nơi giữ trẻ": "Find Childcare",

  // Marketing
  "⚠️ Chế độ dùng thử (Cấu hình xác thực Clerk từ xa hiện chưa sẵn sàng)":
    "⚠️ Trial mode (Remote Clerk authentication config is not ready yet)",
  "Trợ lý sức khỏe nhi khoa thông minh dựa trên trí tuệ nhân tạo. Tra cứu chính xác nguồn tham chiếu, bảo bối đắc lực cho cha mẹ trong việc chăm sóc và theo dõi sức khỏe của bé yêu, đáng tin cậy kể cả lúc 3 giờ sáng.":
    "An intelligent AI-powered pediatric health assistant. Look up accurate references — a trusted companion for parents caring for and monitoring your little one's health, dependable even at 3 a.m.",
  "Bắt đầu trò chuyện": "Start chatting",
  "Tạo tài khoản mới": "Create new account",
  "Nguồn tài liệu chính thống, cập nhật mới nhất": "Official, up-to-date sources",
  "Trải nghiệm mượt mà": "Smooth experience",

  // HomeHub
  "Bắt đầu chăm sóc con yêu tốt hơn": "Start caring for your child better",
  "Xin chào, {userName}! 👋": "Hello, {userName}! 👋",
  "HealthyLung đồng hành cùng bạn chăm sóc sức khỏe cho bé từ 0 - 12 tuổi. Hãy hỏi tôi về triệu chứng, liều lượng vắc-xin, chế độ dinh dưỡng hoặc tìm phòng khám nhi và trường học gần nhất.":
    "HealthyLung accompanies you in caring for your child's health from 0 - 12 years old. Ask me about symptoms, vaccine dosages, nutrition, or find nearby pediatric clinics and schools.",
  "Bắt đầu trò chuyện mới": "Start a new chat",
  "Góc chia sẻ từ cha mẹ khác": "Tips from other parents",
  "Các tính năng chính": "Main features",
  "Tư vấn Sức khỏe AI": "AI Health Consultation",
  "Hỏi đáp triệu chứng, chẩn đoán sơ bộ, điều trị và chăm sóc bé tại nhà. Câu trả lời chính xác, được kiểm chứng dựa trên thông tin y khoa của hệ thống đa nguồn.":
    "Q&A about symptoms, preliminary diagnosis, treatment and home care. Accurate answers verified against medical information from a multi-source system.",
  "Cộng đồng Chia sẻ": "Sharing Community",
  "Xem các thắc mắc phổ biến, tâm sự và kinh nghiệm của các cha mẹ Việt khác. Bạn có thể sử dụng lại câu hỏi thảo luận chỉ với đúng một nhấp chuột tiện lợi.":
    "Browse common questions, stories and experiences from other Vietnamese parents. You can reuse any discussion question with a single convenient click.",
  "Tìm nơi Y tế & Giữ trẻ": "Find Healthcare & Childcare",
  "Xác định vị trí tự động hoặc thủ công để tìm các bệnh viện nhi, phòng khám đa khoa chất lượng, nhà trẻ, trường mầm non và dịch vụ bảo mẫu xung quanh bạn.":
    "Detect your location automatically or manually to find pediatric hospitals, quality general clinics, daycares, preschools and babysitting services around you.",

  // ChatWorkspace
  "Không thể tải danh sách cuộc trò chuyện. Hãy thử lại.":
    "Could not load the conversation list. Please try again.",
  "Không thể tìm thấy hoặc tải chi tiết cuộc trò chuyện. Hãy thử lại.":
    "Could not find or load the conversation details. Please try again.",
  "HealthyLung đang tra cứu nguồn liên quan và soạn phản hồi cho bạn...":
    "HealthyLung is looking up relevant sources and composing a response for you...",
  "Cuộc trò chuyện mới": "New conversation",
  "Yêu cầu tư vấn thất bại. Hãy thử lại hoặc tối giản câu hỏi của bạn.":
    "Consultation request failed. Please try again or simplify your question.",
  "Cập nhật quyền truy cập liên kết thất bại.": "Failed to update link access.",
  "Bạn có chắc chắn muốn xóa vĩnh viễn cuộc trò chuyện y tế này?":
    "Are you sure you want to permanently delete this medical conversation?",
  "Xóa cuộc trò chuyện thất bại.": "Failed to delete the conversation.",
  "Cha mẹ HealthyLung": "HealthyLung Parent",
  "Lịch sử tư vấn": "Consultation history",
  "Đang tải danh sách...": "Loading list...",
  "Chưa có cuộc trò chuyện nào. Hãy gửi tin nhắn đầu tiên!":
    "No conversations yet. Send your first message!",
  "Cuộc trò chuyện ẩn danh": "Untitled conversation",
  "Bất kỳ ai có liên kết đều xem được": "Anyone with the link can view",
  "Mở": "Open",
  "Chỉ mình tôi xem được": "Only I can view",
  "Riêng tư": "Private",
  "{n} tin": "{n} msgs",
  "Xóa cuộc trò chuyện này": "Delete this conversation",
  "Xóa": "Delete",
  "Lịch sử": "History",
  "Trò chuyện mới": "New chat",
  "Đọc nguồn ({n})": "View sources ({n})",
  "Chào {userName}, tôi là HealthyLung AI!": "Hi {userName}, I'm HealthyLung AI!",
  "Tôi tự động phân tích câu hỏi của bạn, truy cập khối thông tin chính thống từ Vinmec và các nguồn nhi khoa lâm sàng để tìm giải pháp chu đáo nhất. Thử đặt câu hỏi dưới đây:":
    "I automatically analyze your question, accessing official information from Vinmec and clinical pediatric sources to find the most thoughtful solution. Try asking a question below:",
  "Trẻ 6 tháng tuổi sốt 38.5 độ phát ban đỏ cần chăm sóc thế nào?":
    "How should I care for a 6-month-old with a 38.5°C fever and a red rash?",
  "Dấu hiệu cấp cứu khẩn cấp khi bé sơ sinh bị tiêu chảy?":
    "What are emergency warning signs when a newborn has diarrhea?",
  "Bé biếng ăn dặm, chậm tăng cân cần bổ sung dinh dưỡng gì?":
    "My baby refuses solids and gains weight slowly — what nutrition should I add?",
  "Bạn": "You",
  "Chi tiết nguồn": "Source details",
  "HealthyLung đang phân loại triệu chứng lâm sàng và tổng hợp tài liệu...":
    "HealthyLung is classifying clinical symptoms and compiling references...",
  "Ví dụ: Bé nhà mình bị ho khan kéo dài 3 ngày...":
    "e.g. My child has had a dry cough for 3 days...",
  "Gửi câu hỏi": "Send question",
  "Gửi": "Send",
  "Để gửi: nhấn Enter · Để xuống dòng: nhấn Shift + Enter":
    "To send: press Enter · New line: Shift + Enter",
  "Dữ liệu lâm sàng tự động cập nhật liên tục": "Clinical data updates automatically",
  "Bảng Kiểm Chứng Nguồn": "Source Verification Panel",
  "Hướng Trả Lời:": "Answer focus:",
  "Cơ sở dữ liệu y khoa đề xuất trọng tâm phân tích thuộc nhóm đặc tính:":
    "The medical database suggests the analysis focus belongs to the group:",
  "Cơ sở phân loại": "Classification basis",
  "Cảnh báo Y tế Lâm sàng": "Clinical Medical Warning",
  "Thông tin từ HealthyLung AI chỉ mang tính chất tham khảo, không thay thế cho chẩn đoán chuyên môn của bác sĩ.":
    "Information from HealthyLung AI is for reference only and does not replace a doctor's professional diagnosis.",
  "Đỏ khẩn cấp:": "Emergency red flag:",
  "Nếu trẻ xuất hiện co giật, li bì, khó thở rít, mất nước nặng, hãy gọi ngay cấp cứu hoặc tới bệnh viện nhi khoa gần nhất.":
    "If the child has convulsions, lethargy, stridor, or severe dehydration, call emergency services immediately or go to the nearest pediatric hospital.",
  "Đối chiếu kỹ nội dung các bài viết của y sĩ chuyên khoa trước khi tự áp dụng tại nhà.":
    "Carefully cross-check specialist articles before applying anything at home.",
  "Liên kết chia sẻ công khai": "Public share link",
  "Công khai": "Public",
  "Bật chế độ công khai để lưu lại đường dẫn chia sẻ bài tư vấn này cho người thân.":
    "Enable public mode to save a shareable link to this consultation for your family.",
  "Hủy chia sẻ công khai": "Stop public sharing",
  "Kích hoạt chia sẻ": "Enable sharing",
  "Sao chép liên kết": "Copy link",
  "Đã sao chép!": "Copied!",
  "Nguồn tham chiếu y khoa ({n})": "Medical references ({n})",
  "Mức tin cậy: {score}": "Confidence: {score}",
  "Chưa có điểm": "No score",
  "Điểm: {score}": "Score: {score}",
  "{n} đoạn trích": "{n} excerpts",
  "Tìm bái trên Vinmec": "Search on Vinmec",
  "Mở bài gốc từ sở y tế": "Open original from health source",
  "Tài liệu nội bộ được bảo vệ bản quyền.": "Internal copyrighted document.",
  "Chọn tin nhắn câu trả lời của ": "Select a ",
  " để tra cứu chi tiết nguồn tài liệu lâm sàng tham khảo.":
    " answer message to look up detailed clinical reference sources.",
  "Lịch sử cuộc gọi": "Conversation history",
  "Đóng": "Close",
  "Kiểm chứng thông tin": "Verify information",
  "Hướng:": "Focus:",
  "Cảnh báo": "Warning",
  "Nội dung chỉ tham khảo. Gọi cấp cứu y tế nếu bé gặp biểu hiện thở rít, li bì, co giật.":
    "For reference only. Call emergency services if the child shows stridor, lethargy, or convulsions.",
  "Mở liên kết gốc": "Open original link",
  "Nhấn vào bong bóng câu trả lời ở luồng để đọc nguồn gốc y văn.":
    "Tap an answer bubble in the thread to read the medical sources.",

  // Community
  "Tất cả chủ đề": "All topics",
  "Triệu chứng & sốt": "Symptoms & fever",
  "Dinh dưỡng & ăn dặm": "Nutrition & weaning",
  "Trẻ sơ sinh": "Newborns",
  "Vắc-xin & Phòng ngừa": "Vaccines & Prevention",
  "Góc chia sẻ kinh nghiệm": "Experience sharing corner",
  "Diễn đàn Cha Mẹ HealthyLung": "HealthyLung Parents Forum",
  "Nơi tổng hợp các nội dung tư vấn y khoa công khai, bổ ích được lưu trữ từ cộng đồng các ông bố bà mẹ bỉm sữa Việt.":
    "A hub of public, helpful medical consultations saved from the community of Vietnamese parents.",
  "Mở cuộc tư vấn mới": "Start a new consultation",
  "Danh sách chia sẻ cộng đồng": "Community sharing list",
  "Hỏi:": "Question:",
  "HealthyLung AI tư vấn (Dựa trên tài liệu kiểm chứng)":
    "HealthyLung AI advice (Based on verified sources)",
  "Cảm ơn": "Thanks",
  "Thảo luận": "Discussion",
  "{n} bình luận": "{n} comments",
  "Dùng lại câu hỏi": "Reuse question",

  // FindCare
  "Tất cả": "All",
  "Nhà trẻ": "Daycare",
  "Trường mầm non": "Preschool",
  "Trực trông trẻ": "Babysitter",
  "Bệnh viện": "Hospital",
  "Phòng khám nhi": "Pediatric clinic",
  "Trình duyệt này không hỗ trợ định vị địa lý.": "This browser does not support geolocation.",
  "Không thể lấy vị trí từ thiết bị của bạn. Vui lòng bật định vị hoặc chọn tọa độ mẫu của chúng tôi.":
    "Could not get your device location. Please enable location or pick one of our sample coordinates.",
  "Cha mẹ chưa cấp quyền vị trí. Nhấn tọa độ mẫu để tiếp tục tra cứu nhanh chóng.":
    "Location permission was not granted. Tap a sample coordinate to continue quickly.",
  "Xảy ra lỗi khi tìm kiếm cơ sở giữ trẻ và y khoa. Sử dụng kết quả dự phòng.":
    "An error occurred while searching for childcare and medical facilities. Showing fallback results.",
  "Dữ liệu bản đồ tự do OSM": "Free OSM map data",
  "Tiện ích định vị vùng lân cận": "Nearby location finder",
  "Bản Đồ Y Tế & Chăm Sóc Trẻ": "Healthcare & Childcare Map",
  "Quét bán kính 5 km xung quanh vị trí hiện tại để tìm nhanh bệnh viện nhi, khoa y tế cộng đồng, nhà trẻ đáng tin cậy.":
    "Scan a 5 km radius around your current location to quickly find pediatric hospitals, community health units, and trusted daycares.",
  "Đang xác vị trí...": "Locating...",
  "Sử dụng vị trí của tôi": "Use my location",
  "Đã thu nhận tọa độ ({lat}, {lng}) · Sai số {acc}m · Bán kính 5km":
    "Coordinates acquired ({lat}, {lng}) · Accuracy {acc}m · Radius 5km",
  "Chờ cung cấp tọa độ...": "Waiting for coordinates...",
  "Thử toạ độ mẫu:": "Try sample coordinates:",
  "Hà Nội": "Hanoi",
  "Sài Gòn": "Saigon",
  "Mở bán kính 5km trên Google Maps vệ tinh": "Open 5km radius on Google Maps satellite",
  "Lọc nhanh theo tên cơ sở, địa chỉ chi tiết, loại dịch vụ...":
    "Quick filter by facility name, address, or service type...",
  "Số lượng đã tìm thấy": "Number found",
  "Tìm thấy: {n} địa điểm": "Found: {n} places",
  "Đang rà soát bản đồ tọa độ y văn...": "Scanning the medical map...",
  "Không tìm thấy địa điểm nào quanh đây": "No places found nearby",
  "Hiện chưa có hồ sơ lưu trữ nào khớp với bộ lọc bạn chọn trong phạm vi bán kính 5km. Hãy thử chọn tọa độ mẫu Hà Nội/Sài Gòn hoặc nới rộng cụm từ cần tìm.":
    "No saved records match your filter within the 5km radius. Try a Hanoi/Saigon sample coordinate or broaden your search terms.",
  "Kết quả tìm kiếm": "Search results",
  "Chuyên mục:": "Category:",
  "Khoảng cách:": "Distance:",
  "mét": "m",
  "Xem Trang chủ": "Visit website",
  "Chỉ đường": "Directions",
  "Trao đổi chuyên môn": "Discuss with AI",
  "Kết quả định vị địa điểm nhi học và dịch vụ chăm sóc sức khỏe nhi được trích xuất an toàn từ:":
    "Pediatric locations and child healthcare services are safely sourced from:",

  // SharedConversation
  "Liên kết chia sẻ này hiện không khả dụng.": "This share link is currently unavailable.",
  "Không tìm thấy cuộc trò chuyện được chia sẻ.": "Shared conversation not found.",
  "Đã xảy ra lỗi không thể xác định khi kết nối với máy chủ.":
    "An unknown error occurred while connecting to the server.",
  "Bản Chia Sẻ": "Shared",
  "Về trang chính": "Back to home",
  "Đang bảo mật nạp dữ liệu chia sẻ...": "Securely loading shared data...",
  "Truy cập thất bại": "Access failed",
  "Quay lại Trang chủ": "Back to Home",
  "Ngày chia sẻ công khai: {date} · {n} lượt hội thoại":
    "Publicly shared on: {date} · {n} messages",
  "Chủ đề thảo luận": "Discussion topic",
  "Tư vấn Nhi khoa": "Pediatric consultation",
  "Người dùng chia sẻ": "Shared by user",
  "HealthyLung AI tư vấn": "HealthyLung AI advice",
  "🔍 Nhấp xem nguồn": "🔍 Tap to view sources",
  "Kiểm Định Y Văn (Read-Only)": "Source Audit (Read-Only)",
  "Phán đoán trọng điểm:": "Key assessment:",
  "Cảnh báo Nhi khoa Lâm sàng": "Clinical Pediatric Warning",
  "Nội dung chia sẻ chỉ có ý nghĩa tham khảo. Nếu bé mệt sâu, li bì, mất nước nặng hay co giật, cần nhanh chóng liên hệ với cơ sở cấp cứu y tế gần nhất.":
    "Shared content is for reference only. If the child is very weak, lethargic, severely dehydrated, or convulsing, contact the nearest emergency facility immediately.",
  "Y văn đối sánh y tế ({n})": "Matched medical sources ({n})",
  "Mức độ tin cậy: {score}": "Confidence level: {score}",
  "Xem bài viết từ Vinmec": "View article from Vinmec",
  "Chọn một bong bóng phản hồi ở luồng để nạp chứng thực y khoa.":
    "Select a response bubble in the thread to load medical evidence.",
  "Chứng thực tài liệu": "Document verification",
  "Phán đoán:": "Assessment:",

  // Type label maps (passed through getLabel -> t)
  "Triệu chứng": "Symptoms",
  "Nguyên nhân": "Causes",
  "Điều trị": "Treatment",
  "Chẩn đoán": "Diagnosis",
  "Phòng ngừa": "Prevention",
  "Lây truyền": "Transmission",
  "Nguy cơ": "Risk factors",
  "Tổng quan": "Overview",
  "Tổng quát": "General",
  "Nội dung chính": "Main content",
  "Tiểu mục": "Subsection",
  "Bài viết nhi khoa Vinmec": "Vinmec pediatric articles",
  "Bài viết bệnh lý Vinmec": "Vinmec disease articles",
  "Hướng dẫn thuốc Vinmec": "Vinmec medication guide",
  "Bài viết Cơ thể người Vinmec": "Vinmec human body articles",
  "Kho Nhi khoa và Bệnh lý": "Pediatrics & Pathology store",
  "Kho Nhi khoa": "Pediatrics store",
  "Kho Bệnh lý": "Pathology store",
  "Kho Thuốc và Vật tư y tế": "Medication & Supplies store",
  "Kho Cơ thể người": "Human Body store",
};

const DOC_TITLE: Record<Lang, string> = {
  vi: "HealthyLung – Trợ lý Sức khỏe Nhi khoa AI",
  en: "HealthyLung – AI Pediatric Health Assistant",
};

type Vars = Record<string, string | number>;

// Pure translator: vi is passthrough, en falls back to vi when unmapped.
export function translate(dict: Record<string, string>, lang: Lang, vi: string, vars?: Vars): string {
  let s = lang === "en" ? dict[vi] ?? vi : vi;
  if (vars) {
    for (const k of Object.keys(vars)) {
      s = s.split(`{${k}}`).join(String(vars[k]));
    }
  }
  return s;
}

interface LangContextValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggle: () => void;
  t: (vi: string, vars?: Vars) => string;
}

const LangContext = createContext<LangContextValue | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "en" || stored === "vi" ? stored : "vi";
  });

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem(STORAGE_KEY, l);
  }, []);

  const toggle = useCallback(() => setLang(lang === "vi" ? "en" : "vi"), [lang, setLang]);

  const t = useCallback((vi: string, vars?: Vars) => translate(EN, lang, vi, vars), [lang]);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = DOC_TITLE[lang];
  }, [lang]);

  return <LangContext.Provider value={{ lang, setLang, toggle, t }}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) {
    throw new Error("useLang must be used within a LangProvider");
  }
  return ctx;
}

export function LangToggle({ className }: { className?: string }) {
  const { lang, toggle } = useLang();
  return (
    <button
      type="button"
      onClick={toggle}
      className={className ?? "btn btn-secondary btn-pill btn-sm"}
      id="lang-toggle-btn"
      title={lang === "vi" ? "Switch to English" : "Chuyển sang Tiếng Việt"}
      aria-label="Toggle interface language"
      style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "6px 12px" }}
    >
      <Languages style={{ width: "16px", height: "16px" }} />
      {lang === "vi" ? "EN" : "VI"}
    </button>
  );
}

// ponytail: dev-only self-check — the smallest thing that fails if translate() breaks.
if ((import.meta as any).env?.DEV) {
  console.assert(translate({ a: "b" }, "en", "a") === "b", "i18n: en lookup");
  console.assert(translate({}, "en", "x") === "x", "i18n: en fallback to vi");
  console.assert(translate({}, "vi", "y") === "y", "i18n: vi passthrough");
  console.assert(translate({}, "en", "Hi {n}", { n: 5 }) === "Hi 5", "i18n: interpolation");
}
