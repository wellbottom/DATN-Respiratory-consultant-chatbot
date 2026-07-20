import { useEffect } from "react";
import { X } from "lucide-react";

import {
  CORPUS_LABELS,
  SECTION_TYPE_LABELS,
  SourceSection,
  getLabel
} from "../types";
import { useLang } from "../i18n";

interface SourceDetailsModalProps {
  source: SourceSection | null;
  sourceLabel: string;
  onClose: () => void;
}

export function SourceDetailsModal({ source, sourceLabel, onClose }: SourceDetailsModalProps) {
  const { t } = useLang();

  useEffect(() => {
    if (!source) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [source, onClose]);

  if (!source) return null;

  const chunksWithContent = source.chunks.filter((chunk) => (chunk.content || "").trim());

  return (
    <div className="source-modal-backdrop" role="presentation" onClick={onClose}>
      <section
        className="source-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="source-modal-header">
          <div>
            <span className="overline">{t(getLabel(source.corpus, CORPUS_LABELS))}</span>
            <h3 id="source-modal-title">{sourceLabel}</h3>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label={t("Đóng")}>
            <X />
          </button>
        </div>

        <dl className="source-detail-grid">
          <div>
            <dt>{t("Loại mục")}</dt>
            <dd>{t(getLabel(source.section_type, SECTION_TYPE_LABELS))}</dd>
          </div>
          {source.h2 && (
            <div>
              <dt>{t("Mục")}</dt>
              <dd>{source.h2}</dd>
            </div>
          )}
          {source.h3 && (
            <div>
              <dt>{t("Tiểu mục")}</dt>
              <dd>{source.h3}</dd>
            </div>
          )}
        </dl>

        {chunksWithContent.length > 0 ? (
          <div className="source-chunks-box">
            <span className="overline">{t("Nội dung truy xuất")}</span>
            {chunksWithContent.map((chunk) => (
              <article key={chunk.chunk_id} className="source-chunk-content">
                <div className="source-chunk-meta">
                  <span>
                    {t("Đoạn")} {chunk.candidate_chunk_index}/{chunk.candidate_chunk_total}
                  </span>
                </div>
                <p>{chunk.content}</p>
              </article>
            ))}
          </div>
        ) : (
          <div className="source-chunks-box">
            <span className="caption">{t("Nguồn cũ chưa lưu nội dung chunk. Hãy gửi lại câu hỏi để xem nội dung truy xuất.")}</span>
            {source.chunks.map((chunk) => (
              <div key={chunk.chunk_id} className="source-chunk-row">
                <span>
                  {t("Đoạn")}{" "}
                  {chunk.candidate_chunk_index}/{chunk.candidate_chunk_total}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
