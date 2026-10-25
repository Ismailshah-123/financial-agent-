# Finance AI Control Center — React

Production React/Vite frontend for the Finance AI Platform. It communicates only with the FastAPI API; it does not connect directly to PostgreSQL, Redis, Qdrant, or SAP.

## Run

```bash
cd frontend
npm install
npm run dev
```

The dev server uses port `3000` so it matches the example backend CORS origin. Set `VITE_API_BASE_URL` when the API is elsewhere:

```bash
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

## Build

```bash
npm run build
```

`robots.txt` intentionally blocks indexing because this is a private finance console. The app sets `noindex, nofollow, noarchive` at document level as well. This is the correct SEO posture for an authenticated finance product; the public Vertex marketing site should own discoverable SEO.

## Application areas

Overview, Receivables, Customer Detail, Payables, Approval Inbox, AI Agent Center, Reports, SAP Business One Integration, and Settings. All displayed finance values come from backend endpoints; the React layer does not duplicate accounting logic.
