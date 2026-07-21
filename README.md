# Thiết lập RAG Web App

Repo này chạy workflow:

```text
markdown -> chunking -> indexing -> Chroma -> web_app
```

## Cấu trúc

```text
data/markdown/                 # Tài liệu markdown đầu vào
data/chunks/                   # Chunk JSONL sinh ra từ setup
data/indexes/                  # Index local: chunks.jsonl, vectors.npy, lexical.sqlite3
data/chroma_manifests/         # Manifest Chroma local
scripts/RAG/                   # Chunking, embedding, indexing, retriever, Chroma sync
web_app/                       # FastAPI backend + frontend dist
scripts/setup.ps1              # Cài đặt + build RAG index + sync Chroma
scripts/run_webapp.ps1         # Chạy ứng dụng
```

## Yêu cầu

- Windows PowerShell
- Python 3.10+
- Node.js LTS và npm
- Internet nếu dùng `siliconflow`
- API keys cho web app:
  - `SILICONFLOW_API_KEY`
  - `GROQ_API_KEY`

## Cài đặt từ Git

Sau khi clone repository, mở PowerShell tại thư mục gốc:

```powershell
Copy-Item .env.example .env
notepad .env
```

Điền các key:

```env
SILICONFLOW_API_KEY=your_key
GROQ_API_KEY=your_key
```

Sau đó cài dependencies, build frontend và toàn bộ RAG pipeline:

```powershell
.\scripts\setup.ps1
```

Script sẽ:

1. Tạo `.venv`
2. Cài dependencies từ `requirements.txt`
3. Chạy `npm ci` và build frontend
4. Chunk file trong `data\markdown`
5. Tạo dense index và `lexical.sqlite3` trong `data\indexes\local_rag`
6. Sync vào Chroma local tại `web_app\storage\chroma`
7. Ghi manifest Chroma tại `data\chroma_manifests\local_rag.json`
8. Kiểm tra frontend, dense/lexical index và collection `local_rag`

Sau khi chạy thành công, các file/thư mục chính phải có:

```text
data\chunks\local_rag.chunks.jsonl
data\chunks\local_rag.chunks.stats.json
data\indexes\local_rag\chunks.jsonl
data\indexes\local_rag\vectors.npy
data\indexes\local_rag\lexical.sqlite3
data\indexes\local_rag\manifest.json
web_app\frontend\dist\index.html
web_app\storage\chroma\
data\chroma_manifests\local_rag.json
```

Lưu ý: không dùng `.\scripts\setup.ps1 -SkipPipeline` trong lần cài đầy đủ đầu tiên vì tùy chọn này không tạo RAG index và Chroma local.

## Chạy web app

```powershell
.\scripts\run_webapp.ps1
```

Mở:

```text
http://127.0.0.1:8002
```

Chạy port khác:

```powershell
.\scripts\run_webapp.ps1 -Port 8002
```

## Tuỳ chọn Ollama local

Nếu muốn embed local bằng Ollama:

```powershell
ollama pull qwen3-embedding:4b
.\scripts\setup.ps1 -EmbeddingBackend ollama -EmbeddingModel qwen3-embedding:4b -EmbeddingBatchSize 8
```

## Rebuild khi đổi tài liệu

Thêm/sửa file `.md` trong:

```text
data\markdown
```

Rồi chạy lại:

```powershell
.\scripts\setup.ps1
```

## Kiểm tra nhanh

Kiểm tra Python files:

```powershell
.\.venv\Scripts\python -m compileall -q scripts web_app
```

Truy vấn thử Chroma:

```powershell
.\.venv\Scripts\python -m scripts.RAG.vectordatabase query `
  --collection local_rag `
  --persist-path web_app\storage\chroma `
  --query "điều trị hen phế quản" `
  --top-k 5
```

Truy vấn thử index local:

```powershell
.\.venv\Scripts\python -m scripts.RAG.retriever `
  --index-dir data\indexes\local_rag `
  --query "điều trị hen phế quản" `
  --top-k 5
```

## Lỗi thường gặp

`Hãy đặt SILICONFLOW_API_KEY...`

- Điền `SILICONFLOW_API_KEY` vào `.env`, hoặc dùng Ollama local.

`Không tìm thấy môi trường ảo`

- Chạy `.\scripts\setup.ps1` trước.

`Clerk chưa được cấu hình xác thực`

- Web app gốc có auth Clerk. Cần thêm `CLERK_JWT_KEY` hoặc `CLERK_FRONTEND_API_URL`/`CLERK_JWKS_URL` nếu dùng các endpoint cần đăng nhập.

`Không tìm thấy collection`

- Chạy lại `.\scripts\setup.ps1` để sync Chroma.
- Nếu trước đó chỉ chạy `.\scripts\setup.ps1 -SkipPipeline` thì Chroma chưa được tạo.

## Lấy key Clerk

Setup mặc định chưa có key Clerk. `scripts\setup.ps1` chỉ tạo sẵn các dòng trống cho `SILICONFLOW_API_KEY` và `GROQ_API_KEY`, nên nếu dùng đăng nhập Clerk thì cần tự thêm vào `.env`.

1. Vào Clerk Dashboard: https://dashboard.clerk.com
2. Chọn app/project đang dùng.
3. Mở trang **API keys**.
4. Copy **Publishable key** vào `.env`:

```env
CLERK_PUBLISHABLE_KEY=pk_test_...
```

5. Để backend verify token, đặt một trong hai cách sau:

```env
CLERK_FRONTEND_API_URL=https://<your-instance>.clerk.accounts.dev
```

hoặc:

```env
CLERK_JWKS_URL=https://<your-instance>.clerk.accounts.dev/.well-known/jwks.json
```

Clerk docs: https://clerk.com/docs/guides/development/clerk-environment-variables và https://clerk.com/docs/guides/sessions/manual-jwt-verification.

## Deploy Vercel với Supabase và Chroma Cloud

Vercel build frontend và chạy FastAPI trong cùng một project. Import repository với
thư mục gốc là repository root; không đặt Root Directory thành `web_app/frontend`.

Đặt các Environment Variables cho Production và Preview trong Vercel:

```env
DATABASE_URL=postgresql://postgres.PROJECT_REF:<PASSWORD_URL_ENCODED>@HOST:6543/postgres?sslmode=require
CHROMA_API_KEY=
WEBAPP_CHROMA_MODE=cloud
WEBAPP_CHROMA_TENANT=
WEBAPP_CHROMA_DATABASE=Respiratory
SILICONFLOW_API_KEY=
GROQ_API_KEY=
CLERK_PUBLISHABLE_KEY=
CLERK_JWKS_URL=
CLERK_ALLOWED_ORIGINS=https://YOUR_PROJECT.vercel.app
```

Nếu mật khẩu PostgreSQL chứa `@`, thay ký tự đó bằng `%40` trong `DATABASE_URL`.
Không thêm dấu nháy quanh giá trị trong Vercel. Dùng Transaction pooler port `6543`
và `sslmode=require` cho Supabase.

Sau khi deploy, kiểm tra:

```text
https://YOUR_PROJECT.vercel.app/api/health
```

Kết quả mong đợi là `{"status":"ok"}`. Sau đó đăng nhập bằng Clerk và gửi một tin
nhắn để xác nhận hội thoại được lưu trong Supabase và truy hồi từ collection
`local_rag` trên Chroma Cloud.
