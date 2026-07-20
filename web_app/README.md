# Web App

`web_app` là ứng dụng FastAPI + React/Vite cho RAG chat:

- Frontend React + Vite trong `web_app/frontend`
- Backend FastAPI trong `web_app/backend`
- Lưu hội thoại bằng SQLAlchemy
- Đăng nhập OAuth qua Clerk
- Truy hồi qua Chroma và sinh câu trả lời qua client LLM chung ở `scripts/RAG/generator.py`

## Chạy ứng dụng

Từ repo root:

```powershell
.\scripts\setup.ps1
.\scripts\run_webapp.ps1
```

`.\scripts\setup.ps1` sẽ tạo index, sync collection `local_rag` vào Chroma local tại `web_app\storage\chroma`, rồi kiểm tra collection có record trước khi báo thành công.

Nếu chỉ muốn tạo `.venv`, cài package và chuẩn bị `.env` để điền key trước, dùng:

```powershell
.\scripts\setup.ps1 -SkipPipeline
```

Lệnh `-SkipPipeline` không tạo Chroma local, nên chưa đủ để chạy RAG.

Mở:

```text
http://127.0.0.1:8001
```

Chạy frontend dev mode nếu cần sửa UI:

```powershell
cd web_app\frontend
npm install
npm run dev
```

## Biến môi trường

Bắt buộc cho RAG/LLM:

- `SILICONFLOW_API_KEY`
- `GROQ_API_KEY`

LLM mặc định dùng Groq:

```env
GROQ_API_KEY=your_key
```

Bắt buộc cho Clerk frontend:

- `CLERK_PUBLISHABLE_KEY`

Backend verify Clerk cần một trong các biến:

- `CLERK_JWT_KEY`
- `CLERK_FRONTEND_API_URL`
- `CLERK_JWKS_URL`

Tuỳ chọn:

- `WEBAPP_DATABASE_URL` hoặc `DATABASE_URL`
- `WEBAPP_DATABASE_PATH`

## Kiểm tra nhanh

Từ repo root:

```powershell
.\.venv\Scripts\python -m compileall -q scripts web_app
.\.venv\Scripts\python scripts\RAG\self_check_roles.py
```

Từ `web_app/frontend`:

```powershell
npm run lint
npm run build
```

## API chính

- `GET /api/conversations`: lấy danh sách hội thoại của user đang đăng nhập
- `POST /api/conversations`: tạo hội thoại mới
- `GET /api/conversations/{conversation_id}`: lấy lịch sử hội thoại
- `POST /api/messages/{conversation_id}`: gửi tin nhắn mới cho chatbot
- `PUT /api/conversations/{conversation_id}`: bật/tắt chia sẻ công khai
- `DELETE /api/conversations/{conversation_id}`: xoá hội thoại

## Ghi chú

- Setup không tạo hoặc ghi token LLM nữa.
- `.env` chỉ giữ API key; endpoint/model mặc định nằm trong settings.
- Toàn bộ logic gọi LLM dùng `RequestLLMClient` trong `scripts/RAG/generator.py`.
- Link chia sẻ công khai có dạng `/share/{conversation_id}`.
