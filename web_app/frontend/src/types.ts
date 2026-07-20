export interface ConversationSummary {
  id: string;
  title: string;
  is_public: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface RouteDebug {
  collection_name?: string;
  knowledge_base?: string;
  corpora: string[];
  intent: string;
  section_types: string[];
  reasons: string[];
}

export interface ChunkInfo {
  chunk_id: string;
  candidate_chunk_index: number;
  candidate_chunk_total: number;
  content?: string | null;
}

export interface SourceSection {
  section_id: string;
  corpus: string;
  title: string;
  h2?: string;
  h3?: string;
  section_type: string;
  source_path: string;
  source_url?: string;
  source_url_kind?: string;
  rerank_score?: number | null;
  vector_score?: number | null;
  vector_distance?: number | null;
  bm25_score?: number | null;
  rrf_score?: number | null;
  chunk_count: number;
  chunks: ChunkInfo[];
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  user_input_id?: string;
  response_id?: string;
  route?: RouteDebug;
  sources?: SourceSection[];
  diagnostics?: Record<string, any>;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
}

export interface MessageResponse {
  conversation: ConversationSummary;
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
  route?: RouteDebug;
  sources?: SourceSection[];
  diagnostics?: Record<string, any>;
}

export interface NearbyService {
  id: string;
  name: string;
  type: string;
  category: string;
  latitude: number;
  longitude: number;
  distance_km: number;
  address?: string;
  phone?: string;
  website?: string;
  opening_hours?: string;
  source_url: string;
  tags: Record<string, any>;
}

export interface NearbyServicesResponse {
  query_latitude: number;
  query_longitude: number;
  category: string;
  radius_m: number;
  source: string;
  results: NearbyService[];
}

// Vietnamese Translation Maps
export const INTENT_LABELS: Record<string, string> = {
  symptom: "Triệu chứng",
  cause: "Nguyên nhân",
  treatment: "Điều trị",
  diagnosis: "Chẩn đoán",
  prevention: "Phòng ngừa",
  transmission: "Lây truyền",
  risk: "Nguy cơ",
  overview: "Tổng quan",
  general: "Tổng quát",
};

export const CORPUS_LABELS: Record<string, string> = {
  vinmec_child_articles: "Bài viết nhi khoa Vinmec",
  vinmec_diseases_articles: "Bài viết bệnh lý Vinmec",
  vinmec_meds_usecase: "Hướng dẫn thuốc Vinmec",
  markdown: "Bài viết Cơ thể người Vinmec",
};

export const COLLECTION_LABELS: Record<string, string> = {
  "vinmec_child_articles,vinmec_diseases_articles": "Kho Nhi khoa và Bệnh lý",
  "vinmec_child_articles": "Kho Nhi khoa",
  "vinmec_diseases_articles": "Kho Bệnh lý",
  "child_care_hybirds": "Kho Nhi khoa và Bệnh lý",
  "meds_guide_hybrid": "Kho Thuốc và Vật tư y tế",
  "vinmec_body_parts": "Kho Cơ thể người",
};

export const SECTION_TYPE_LABELS: Record<string, string> = {
  symptom: "Triệu chứng",
  cause: "Nguyên nhân",
  treatment: "Điều trị",
  diagnosis: "Chẩn đoán",
  prevention: "Phòng ngừa",
  transmission: "Lây truyền",
  risk: "Nguy cơ",
  overview: "Tổng quan",
  article_section: "Nội dung chính",
  subsection: "Tiểu mục",
};

export function getLabel(key: string, map: Record<string, string>): string {
  return map[key] || key;
}
