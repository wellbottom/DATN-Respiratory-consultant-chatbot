# HealthyLung Frontend

Giao diện web cho HealthyLung, xây bằng React + Vite + TypeScript. Frontend nói chuyện với backend FastAPI qua các endpoint `/api/*` và lấy khóa Clerk công khai từ `/api/config/public`.

## Yêu cầu

- Node.js 18+
- Backend FastAPI chạy ở `http://127.0.0.1:8001` (xem `web_app/README.md`)

## Cài đặt

```powershell
cd web_app\frontend
npm install
```

## Chạy dev

```powershell
npm run dev
```

Mở `http://127.0.0.1:5173`. Vite tự proxy mọi request `/api` sang backend FastAPI tại `http://127.0.0.1:8001` (cấu hình trong `vite.config.ts`).

## Build production

```powershell
npm run build
```

Kết quả nằm trong `web_app/frontend/dist`. FastAPI sẽ serve thư mục này và fallback cho các route SPA như `/share/{conversation_id}`.

## Biến môi trường

- `VITE_API_BASE_URL` (tùy chọn): chỉ đặt khi backend nằm ở origin khác. Để trống để dùng cùng origin (production) hoặc dev proxy (development).
- Khóa Clerk được backend cung cấp tại `/api/config/public`, không cần đặt ở frontend.

## Cấu trúc

- `src/main.tsx` – điểm khởi động React
- `src/App.tsx` – boot config, ClerkProvider và routing
- `src/views/` – các trang (HomeHub, ChatWorkspace, Community, FindCare, Marketing, SharedConversation)
- `src/components/` – AppShell, Show
- `src/utils/api.ts` – helper gọi API
- `src/types.ts` – kiểu dữ liệu và nhãn tiếng Việt
- `src/index.css` – hệ thống design (tự định nghĩa, không dùng Tailwind)
