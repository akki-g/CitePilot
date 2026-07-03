# CitePilot Web

Vite + React + TypeScript frontend for the CitePilot proof of concept.

## Getting Started

Run the development server:

```bash
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

Start editing in `src/App.tsx`. The app talks to the FastAPI backend through `VITE_API_BASE_URL`, defaulting to `http://localhost:8000`.

The Docker Compose web service runs the same `pnpm dev` command and binds Vite to `0.0.0.0:3000`.
